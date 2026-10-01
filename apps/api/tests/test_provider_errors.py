from types import SimpleNamespace

import httpx
import pytest
from openai import InternalServerError, RateLimitError

from app.services.summarization import OpenAISummarizer, SummaryError
from app.services.transcription import OpenAITranscriber, TranscriptionError


def provider_error(error_type, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.test"))
    return error_type("simulated provider failure", response=response, body=None)


@pytest.mark.parametrize(
    ("error_type", "status"), [(RateLimitError, 429), (InternalServerError, 500)]
)
def test_stt_429_and_5xx_are_transient(tmp_path, error_type, status):
    transcriber = OpenAITranscriber.__new__(OpenAITranscriber)
    transcriber.model = "fake-model"

    def fail(**kwargs):
        raise provider_error(error_type, status)

    transcriber.client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=fail))
    )
    audio = tmp_path / "chunk.mp3"
    audio.write_bytes(b"sample")
    with pytest.raises(TranscriptionError) as error:
        transcriber.transcribe(audio)
    assert error.value.code == "STT_TEMPORARY" and error.value.transient


@pytest.mark.parametrize(
    ("error_type", "status"), [(RateLimitError, 429), (InternalServerError, 500)]
)
def test_summary_429_and_5xx_are_transient(error_type, status):
    summarizer = OpenAISummarizer.__new__(OpenAISummarizer)
    summarizer.model = "fake-model"

    def fail(**kwargs):
        raise provider_error(error_type, status)

    summarizer.client = SimpleNamespace(responses=SimpleNamespace(create=fail))
    with pytest.raises(SummaryError) as error:
        summarizer._request("transcript", set(), "instructions")
    assert error.value.code == "SUMMARY_TEMPORARY" and error.value.transient
