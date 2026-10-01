import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from app.services import summarization, transcription


def test_whisper_local_uses_loopback_audio_endpoint(tmp_path: Path):
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "Local transcript"})

    transcriber = transcription.WhisperLocalTranscriber.__new__(
        transcription.WhisperLocalTranscriber
    )
    transcriber.model = "whisper-local:base"
    transcriber.request_model = "whisper-1"
    transcriber.client = OpenAI(
        base_url="http://127.0.0.1:7777/v1",
        api_key="local-whisper",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    chunk = tmp_path / "chunk_0000.mp3"
    chunk.write_bytes(b"sample audio")
    assert transcriber.transcribe(chunk) == "Local transcript"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/audio/transcriptions"
    assert b"whisper-1" in requests[0].content


def test_whisper_local_rejects_non_loopback_url(monkeypatch):
    monkeypatch.setattr(
        transcription, "settings", SimpleNamespace(whisper_local_base_url="https://example.com/v1")
    )
    with pytest.raises(transcription.TranscriptionError) as error:
        transcription.WhisperLocalTranscriber()
    assert error.value.code == "LOCAL_STT_URL_INVALID"


def test_kyma_chat_uses_strict_schema_and_validates_result():
    requests = []
    notes = {
        "overview": "The group discussed planning.",
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3.7-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(notes)},
                    }
                ],
            },
        )

    summarizer = summarization.KymaSummarizer.__new__(summarization.KymaSummarizer)
    summarizer.model = "qwen3.7-flash"
    summarizer.check_active = lambda: None
    summarizer.client = OpenAI(
        base_url="https://kymaapi.com/v1",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    result = summarizer._request("transcript", set(), "Only supported claims")
    assert result.overview == notes["overview"]
    assert requests[0]["model"] == "qwen3.7-flash"
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[0]["response_format"]["json_schema"]["strict"] is True


def test_kyma_rejects_invalid_notes():
    summarizer = summarization.KymaSummarizer.__new__(summarization.KymaSummarizer)
    summarizer.model = "qwen3.7-flash"
    summarizer.check_active = None
    summarizer.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            finish_reason="stop",
                            message=SimpleNamespace(
                                content='{"overview":"Only one key"}', refusal=None
                            ),
                        )
                    ]
                )
            )
        )
    )
    with pytest.raises(summarization.SummaryError) as error:
        summarizer._request("transcript", set(), "instructions")
    assert error.value.code == "SUMMARY_INVALID"
