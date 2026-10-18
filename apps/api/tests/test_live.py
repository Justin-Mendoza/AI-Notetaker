import uuid
from types import SimpleNamespace

from test_upload import FakeStorage, create_meeting

from app.api import meetings
from app.main import app
from app.services.storage import get_storage


def post_live(client, meeting_id, key, sequence=0):
    return client.post(
        f"/v1/meetings/{meeting_id}/live-transcript",
        data={"sequence_no": str(sequence)},
        files={"file": ("prefix.webm", bytes.fromhex("1a45dfa3") + b"audio", "audio/webm")},
        headers={"Idempotency-Key": str(key)},
    )


def test_live_minutes_are_owned_idempotent_and_reused_by_final_upload(api_client, monkeypatch):
    client, identity = api_client
    calls = []

    class LocalTranscriber:
        provider = "cohere-local"
        model = "cohere-test"
        client = SimpleNamespace(with_options=lambda **kwargs: None)

        def transcribe(self, path):
            calls.append(path)
            return "A saved minute of class"

    monkeypatch.setattr(meetings, "CohereLocalTranscriber", LocalTranscriber)
    monkeypatch.setattr(
        meetings,
        "settings",
        SimpleNamespace(
            stt_provider="cohere_local",
            max_uploads_per_hour=10,
            max_meetings_per_hour=20,
            failed_audio_retention_days=7,
        ),
    )
    monkeypatch.setattr(
        meetings, "extract_live_window", lambda source, mime, sequence, directory: source
    )
    monkeypatch.setattr(meetings, "inspect_audio", lambda path, mime: ("audio/webm", 65000))
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    meeting_id = create_meeting(client)
    key = uuid.uuid4()
    first = post_live(client, meeting_id, key)
    assert first.status_code == 200
    assert first.json()["text"] == "A saved minute of class"
    assert first.json()["end_ms"] == 60000
    assert post_live(client, meeting_id, key).json()["id"] == first.json()["id"]
    assert len(calls) == 1
    assert post_live(client, meeting_id, uuid.uuid4(), sequence=1).status_code == 409
    assert (
        client.get(f"/v1/meetings/{meeting_id}/live-transcript").json()["full_text"]
        == "A saved minute of class"
    )
    assert post_live(client, meeting_id, key, sequence=1).status_code == 200
    # A quota error or crash may leave less browser audio than the confirmed live transcript.
    monkeypatch.setattr(meetings, "inspect_audio", lambda path, mime: ("audio/webm", 50000))
    owner = identity["owner"]
    identity["owner"] = uuid.uuid4()
    assert post_live(client, meeting_id, key).status_code == 404
    identity["owner"] = owner
    response = client.post(
        f"/v1/meetings/{meeting_id}/recording",
        data={"duration_ms": "65000", "live_transcription": "true"},
        files={"file": ("full.webm", b"audio", "audio/webm")},
        headers={"Idempotency-Key": str(key)},
    )
    assert response.status_code == 202
    assert post_live(client, meeting_id, key, sequence=1).status_code == 409
    assert len(calls) == 2
    assert client.get(f"/v1/meetings/{meeting_id}").json()["meeting"]["duration_ms"] == 120000


def test_live_requests_are_bounded_before_spooling(api_client, monkeypatch):
    client, _ = api_client
    meeting_id = create_meeting(client)
    monkeypatch.setattr("app.size_limit.MAX_UPLOAD_REQUEST_BYTES", 5)
    assert post_live(client, meeting_id, uuid.uuid4()).status_code == 413
