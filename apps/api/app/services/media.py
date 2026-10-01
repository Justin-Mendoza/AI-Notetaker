import json
import math
import subprocess
from pathlib import Path

from app.errors import ApiError

MAX_DURATION_MS = 90 * 60 * 1000
MAX_FILE_BYTES = 100_000_000

MIME_SIGNATURES = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/x-m4a": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
}


def detect_signature(path: Path) -> str | None:
    with path.open("rb") as source:
        header = source.read(16)
    if header.startswith(bytes.fromhex("1a45dfa3")):
        return "webm"
    if header.startswith(b"OggS"):
        return "ogg"
    if header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "wav"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return "mp3"
    return None


def _packet_duration(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        return None
    last = None
    for line in result.stdout.splitlines():
        fields = line.split(",")
        try:
            pts = float(fields[0])
            packet_duration = float(fields[1]) if len(fields) > 1 and fields[1] else 0.0
            last = pts + packet_duration
        except ValueError:
            continue
    return last


def inspect_audio(path: Path, claimed_mime: str) -> tuple[str, int]:
    mime_type = claimed_mime.split(";", 1)[0].strip().lower()
    expected_signature = MIME_SIGNATURES.get(mime_type)
    if expected_signature is None or detect_signature(path) != expected_signature:
        raise ApiError(415, "UNSUPPORTED_MEDIA", "Use a supported audio recording format")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("ffprobe rejected file")
        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        if not any(stream.get("codec_type") == "audio" for stream in streams):
            raise ValueError("missing audio stream")
        if any(stream.get("codec_type") == "video" for stream in streams):
            raise ValueError("video stream is not allowed")
        raw_duration = probe.get("format", {}).get("duration")
        duration = float(raw_duration) if raw_duration not in {None, "N/A"} else None
        if duration is None:
            duration = _packet_duration(path)
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise ValueError("missing duration")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        raise ApiError(415, "INVALID_MEDIA", "The recording could not be read") from exc
    duration_ms = math.ceil(duration * 1000)
    if duration_ms > MAX_DURATION_MS:
        raise ApiError(413, "DURATION_LIMIT", "Recordings must be 90 minutes or shorter")
    return mime_type, duration_ms
