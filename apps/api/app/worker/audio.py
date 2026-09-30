import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

CHUNK_MS = 10 * 60 * 1000
MAX_STT_BYTES = 20_000_000


class AudioProcessingError(Exception):
    pass


@dataclass(frozen=True)
class AudioChunk:
    sequence_no: int
    start_ms: int
    end_ms: int
    path: Path


def run_ffmpeg(args: list[str], timeout: int) -> None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioProcessingError("ffmpeg did not complete") from exc
    if result.returncode != 0:
        raise AudioProcessingError("ffmpeg rejected audio")


def split_audio(source: Path, duration_ms: int, directory: Path) -> list[AudioChunk]:
    """Normalize then create approximate ten-minute MP3 chunks below the STT limit."""
    if duration_ms <= 0:
        raise AudioProcessingError("invalid duration")
    normalized = directory / "normalized.mp3"
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(normalized),
        ],
        timeout=600,
    )
    if not normalized.exists() or normalized.stat().st_size == 0:
        raise AudioProcessingError("normalization produced no audio")
    starts = list(range(0, duration_ms, CHUNK_MS))
    if len(starts) > 1 and duration_ms - starts[-1] < 1000:
        starts.pop()
    chunks = []
    for number, start_ms in enumerate(starts):
        end_ms = min(duration_ms, start_ms + CHUNK_MS)
        if number == len(starts) - 1:
            end_ms = duration_ms
        chunk_path = directory / f"chunk_{number:04d}.mp3"
        run_ffmpeg(
            [
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-i",
                str(normalized),
                "-t",
                f"{(end_ms - start_ms) / 1000:.3f}",
                "-c",
                "copy",
                str(chunk_path),
            ],
            timeout=max(120, math.ceil((end_ms - start_ms) / 1000)),
        )
        if not chunk_path.exists() or not 0 < chunk_path.stat().st_size < MAX_STT_BYTES:
            raise AudioProcessingError("chunk exceeded the STT file limit or was empty")
        chunks.append(AudioChunk(number, start_ms, end_ms, chunk_path))
    return chunks
