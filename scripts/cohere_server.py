"""Loopback-only Cohere Transcribe service, isolated from the application's environment."""

import os
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

MODEL = os.getenv(
    "COHERE_LOCAL_MODEL", "mlx-community/cohere-transcribe-03-2026-mlx-8bit"
)
LANGUAGE = os.getenv("COHERE_LOCAL_LANGUAGE", "en")
MAX_BYTES = 20_000_000
lock = threading.Lock()


class CohereEngine:
    def __init__(self):
        from mlx_audio.stt.models.cohere_asr.vad import SileroMlxBackend
        from mlx_speech.generation import CohereAsrModel

        self.model = CohereAsrModel.from_path(
            Path(__file__).resolve().parents[1] / ".data/cohere-model/mlx-int8"
        )
        self.vad = SileroMlxBackend()
        # Warm the VAD too; startup must fail if either model is missing offline.
        self.vad._load()

    def transcribe(self, path):
        import wave

        import numpy as np
        from mlx_audio.stt.models.cohere_asr.vad import segment_audio

        with wave.open(str(path), "rb") as source:
            waveform = np.frombuffer(
                source.readframes(source.getnframes()), dtype="<i2"
            )
        waveform = waveform.astype(np.float32) / 32768.0
        # The pinned runtime's built-in vad=True mixes MLX and NumPy arrays.
        # Segment explicitly with NumPy and never send more than 35 seconds to ASR.
        runs = segment_audio(waveform, self.vad, merge_gap_s=1.0, max_chunk_s=35.0)
        texts = []
        for run in runs:
            result = self.model.transcribe(
                waveform[run.start_sample : run.end_sample],
                sample_rate=16000,
                language=LANGUAGE,
            )
            if not isinstance(result.text, str):
                raise TypeError("Invalid model output")
            texts.append(result.text.strip())
        return " ".join(text for text in texts if text)


class CohereWorker:
    """MLX streams and model operations stay on their owning thread."""

    def __init__(self, factory=CohereEngine):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cohere-gpu")
        try:
            self.engine = self.pool.submit(factory).result()
        except Exception:
            self.pool.shutdown(wait=True)
            raise

    def transcribe(self, path):
        return self.pool.submit(self.engine.transcribe, path).result()

    def close(self):
        self.pool.shutdown(wait=True)


@asynccontextmanager
async def lifespan(app):
    app.state.engine = CohereWorker()
    try:
        yield
    finally:
        app.state.engine.close()
        app.state.engine = None


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "runtime": "mlx-speech"}


@app.post("/v1/audio/transcriptions")
def transcribe(
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()],
    authorization: Annotated[str | None, Header()] = None,
):
    if authorization != "Bearer local-cohere":
        raise HTTPException(401, "Use the local transcription client")
    if model != MODEL:
        raise HTTPException(400, "Model does not match the loaded Cohere model")
    with tempfile.TemporaryDirectory(prefix="cohere-audio-") as directory:
        source = Path(directory) / "input.audio"
        size = 0
        with source.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Audio chunk is too large")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "Audio chunk is empty")
        wav = Path(directory) / "input.wav"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(wav),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise HTTPException(422, "Audio could not be decoded") from exc
        try:
            with lock:
                text = app.state.engine.transcribe(wav)
            if not isinstance(text, str):
                raise TypeError("Invalid model output")
            return {"text": text.strip()}
        except Exception as exc:
            # Never include class audio, text, or model exception payloads in errors.
            raise HTTPException(503, "Local Cohere transcription failed") from exc
