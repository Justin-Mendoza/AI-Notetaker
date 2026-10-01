from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.settings import settings


class TranscriptionError(Exception):
    def __init__(self, code: str, transient: bool):
        self.code = code
        self.transient = transient
        super().__init__(code)


class Transcriber(Protocol):
    provider: str
    model: str

    def transcribe(self, path: Path) -> str: ...


class OpenAITranscriber:
    provider = "openai"

    def __init__(self):
        if not settings.openai_api_key:
            raise TranscriptionError("PROVIDER_UNAVAILABLE", transient=False)
        self.model = settings.stt_model
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=180, max_retries=0)

    def transcribe(self, path: Path) -> str:
        try:
            with path.open("rb") as source:
                result = self.client.audio.transcriptions.create(
                    model=getattr(self, "request_model", self.model), file=source
                )
            if not isinstance(result.text, str):
                raise TranscriptionError("INVALID_STT_RESPONSE", transient=True)
            return result.text.strip()
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            raise TranscriptionError("STT_TEMPORARY", transient=True) from exc
        except APIStatusError as exc:
            raise TranscriptionError(
                "STT_TEMPORARY" if exc.status_code >= 500 else "STT_REJECTED",
                transient=exc.status_code >= 500,
            ) from exc


class WhisperLocalTranscriber(OpenAITranscriber):
    """Use drajb/whisper-local's loopback-only OpenAI-compatible API."""

    provider = "whisper-local"

    def __init__(self):
        parsed = urlparse(settings.whisper_local_base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path.rstrip("/") != "/v1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise TranscriptionError("LOCAL_STT_URL_INVALID", transient=False)
        self.model = f"whisper-local:{settings.whisper_local_model_label}"
        self.request_model = "whisper-1"
        self.client = OpenAI(
            base_url=settings.whisper_local_base_url,
            api_key="local-whisper",
            timeout=3600,
            max_retries=0,
        )


def create_transcriber() -> Transcriber:
    if settings.stt_provider == "openai":
        return OpenAITranscriber()
    if settings.stt_provider == "whisper_local":
        return WhisperLocalTranscriber()
    raise TranscriptionError("STT_PROVIDER_INVALID", transient=False)


class FakeTranscriber:
    provider = "fake"
    model = "fake-stt-v1"

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.calls: list[int] = []

    def transcribe(self, path: Path) -> str:
        sequence_no = int(path.stem.split("_")[-1])
        self.calls.append(sequence_no)
        return self.texts[sequence_no]
