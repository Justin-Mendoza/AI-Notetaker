import json
import uuid
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
        "topics": [],
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


def test_kyma_retries_altered_evidence_without_saving_it():
    segment_id = uuid.UUID("00000000-0000-4000-8000-000000000002")
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        evidence = "W" + str(segment_id) if len(requests) == 1 else str(segment_id)
        content = {
            "overview": "The group chose a cover.",
            "key_points": [],
            "topics": [],
            "decisions": [{"text": "Use the blue cover.", "evidence_segment_ids": [evidence]}],
            "action_items": [],
            "open_questions": [],
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=json.dumps(content), refusal=None),
                )
            ]
        )

    summarizer = summarization.KymaSummarizer.__new__(summarization.KymaSummarizer)
    summarizer.model = "qwen3.7-flash"
    summarizer.check_active = None
    summarizer.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    result = summarizer._request("synthetic transcript", {segment_id}, "instructions")
    assert result.decisions[0].evidence_segment_ids == [segment_id]
    assert len(requests) == 2
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["decisions"]["items"]["properties"]["evidence_segment_ids"][
        "items"
    ]["enum"] == [str(segment_id)]
    assert schema["properties"]["topics"]["items"]["properties"]["evidence_segment_ids"]["items"][
        "enum"
    ] == [str(segment_id)]
    assert requests[0]["max_tokens"] == 6000


def test_cohere_local_uses_selected_model_and_loopback(monkeypatch, tmp_path):
    monkeypatch.setattr(
        transcription,
        "settings",
        SimpleNamespace(
            cohere_local_base_url="http://127.0.0.1:7778/v1",
            cohere_local_model="cohere-test",
            stt_provider="cohere_local",
        ),
    )
    transcriber = transcription.create_transcriber()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "A local Cohere lecture transcript"})

    transcriber.client = OpenAI(
        base_url="http://127.0.0.1:7778/v1",
        api_key="local-cohere",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    chunk = tmp_path / "chunk_0000.mp3"
    chunk.write_bytes(b"synthetic audio")
    assert transcriber.transcribe(chunk) == "A local Cohere lecture transcript"
    assert transcriber.provider == "cohere-local"
    assert transcriber.model == "cohere-test"
    assert requests[0].url.path == "/v1/audio/transcriptions"
    assert b"cohere-test" in requests[0].content


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://user:pass@localhost/v1",
        "http://localhost/v1?redirect=remote",
    ],
)
def test_cohere_local_rejects_unsafe_urls(monkeypatch, url):
    monkeypatch.setattr(transcription, "settings", SimpleNamespace(cohere_local_base_url=url))
    with pytest.raises(transcription.TranscriptionError) as error:
        transcription.CohereLocalTranscriber()
    assert error.value.code == "LOCAL_STT_URL_INVALID"


def test_kyma_transcription_uses_shared_key_and_selected_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        transcription,
        "settings",
        SimpleNamespace(
            stt_provider="kyma",
            kyma_api_key="test-kyma-key",
            kyma_base_url="https://kymaapi.com/v1",
            kyma_transcription_model="gpt-transcribe",
        ),
    )
    requests = []
    real_client = OpenAI

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "  A binary search tree.  "})

    def client(**kwargs):
        return real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    monkeypatch.setattr(transcription, "OpenAI", client)
    transcriber = transcription.create_transcriber()
    audio = tmp_path / "chunk_0000.mp3"
    audio.write_bytes(b"synthetic audio")
    assert transcriber.transcribe(audio) == "A binary search tree."
    assert transcriber.provider == "kyma"
    assert transcriber.model == "gpt-transcribe"
    assert str(requests[0].url) == "https://kymaapi.com/v1/audio/transcriptions"
    assert requests[0].headers["authorization"] == "Bearer test-kyma-key"
    assert b"gpt-transcribe" in requests[0].content
    assert b"synthetic audio" in requests[0].content


@pytest.mark.parametrize(
    "key,url,code",
    [
        ("", "https://kymaapi.com/v1", "PROVIDER_UNAVAILABLE"),
        ("your-server-only-key", "https://kymaapi.com/v1", "PROVIDER_UNAVAILABLE"),
        ("test-key", "http://example.com/v1", "KYMA_URL_INVALID"),
    ],
)
def test_kyma_transcription_rejects_missing_key_and_wrong_endpoint(monkeypatch, key, url, code):
    monkeypatch.setattr(
        transcription,
        "settings",
        SimpleNamespace(
            kyma_api_key=key,
            kyma_base_url=url,
        ),
    )
    with pytest.raises(transcription.TranscriptionError) as error:
        transcription.KymaTranscriber()
    assert error.value.code == code
    assert not error.value.transient


@pytest.mark.parametrize("status,transient", [(401, False), (429, True), (500, True)])
def test_kyma_transcription_preserves_retry_policy(tmp_path, status, transient):
    transcriber = transcription.KymaTranscriber.__new__(transcription.KymaTranscriber)
    transcriber.model = "gpt-transcribe"
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "simulated failure"}})

    transcriber.client = OpenAI(
        base_url="https://kymaapi.com/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    audio = tmp_path / "chunk_0000.mp3"
    audio.write_bytes(b"synthetic audio")
    with pytest.raises(transcription.TranscriptionError) as error:
        transcriber.transcribe(audio)
    assert error.value.transient is transient
    assert len(requests) == 1
