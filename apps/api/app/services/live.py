"""Extract complete one-minute windows from a growing, independently decodable prefix."""

from pathlib import Path

from app.errors import ApiError
from app.services.media import inspect_audio
from app.worker.audio import AudioProcessingError, run_ffmpeg

LIVE_CHUNK_MS = 60_000


def extract_live_window(source: Path, mime: str, sequence: int, directory: Path) -> Path:
    _, duration = inspect_audio(source, mime)
    end_ms = (sequence + 1) * LIVE_CHUNK_MS
    if duration < end_ms:
        raise ApiError(409, "LIVE_AUDIO_PENDING", "The next audio window is still being captured")
    target = directory / f"chunk_{sequence:04d}.mp3"
    try:
        run_ffmpeg(
            [
                "-ss",
                str(sequence * 60),
                "-i",
                str(source),
                "-t",
                "60",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "32k",
                str(target),
            ],
            timeout=120,
        )
        _, window_duration = inspect_audio(target, "audio/mpeg")
        if window_duration < LIVE_CHUNK_MS - 100:
            raise ApiError(409, "LIVE_AUDIO_PENDING", "The next audio window is incomplete")
    except AudioProcessingError as exc:
        raise ApiError(415, "INVALID_MEDIA", "The audio window could not be decoded") from exc
    return target
