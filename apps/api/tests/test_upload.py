import uuid

from app.api import meetings
from app.errors import ApiError
from app.main import app
from app.services.storage import get_storage


class FakeStorage:
    def __init__(self):
        self.uploaded = []
        self.deleted = []
        self.fail = False

    def upload(self, path, key, mime_type):
        if self.fail:
            raise ApiError(503, "STORAGE_UPLOAD_FAILED", "Upload storage is unavailable")
        self.uploaded.append((key, mime_type, path.read_bytes()))

    def delete(self, key):
        self.deleted.append(key)


def create_meeting(client):
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    assert response.status_code == 201
    return response.json()["meeting"]["id"]


def upload(client, meeting_id, key, data=b"OggS meeting audio", mime="audio/ogg"):
    return client.post(
        f"/v1/meetings/{meeting_id}/recording",
        data={"duration_ms": "2000"},
        files={"file": ("user-controlled-name.ogg", data, mime)},
        headers={"Idempotency-Key": str(key)},
    )


def test_upload_queues_once_and_hides_object_key(api_client, monkeypatch):
    client, identity = api_client
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    monkeypatch.setattr(meetings, "inspect_audio", lambda path, mime: ("audio/ogg", 2000))
    meeting_id = create_meeting(client)
    key = uuid.uuid4()

    first = upload(client, meeting_id, key)
    assert first.status_code == 202
    assert first.json() == {"meeting_id": meeting_id, "status": "queued"}
    assert len(storage.uploaded) == 1
    assert "user-controlled-name" not in storage.uploaded[0][0]
    detail = client.get(f"/v1/meetings/{meeting_id}").json()
    assert detail["meeting"]["status"] == "queued"
    assert detail["job"]["status"] == "pending"
    assert detail["recording"]["size_bytes"] == len(b"OggS meeting audio")
    assert "object_key" not in detail["recording"]

    repeated = upload(client, meeting_id, key, data=b"")
    assert repeated.status_code == 202
    assert len(storage.uploaded) == 1
    assert upload(client, meeting_id, uuid.uuid4()).status_code == 409
    identity["owner"] = uuid.uuid4()
    assert upload(client, meeting_id, key).status_code == 404


def test_upload_rejects_invalid_media_and_resets_draft(api_client):
    client, _ = api_client
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    meeting_id = create_meeting(client)
    response = upload(client, meeting_id, uuid.uuid4(), data=b"not audio", mime="audio/ogg")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA"
    assert client.get(f"/v1/meetings/{meeting_id}").json()["meeting"]["status"] == "draft"
    assert storage.uploaded == []


def test_upload_rejects_oversize_before_storage(api_client, monkeypatch):
    client, _ = api_client
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    monkeypatch.setattr(meetings, "MAX_FILE_BYTES", 4)
    meeting_id = create_meeting(client)
    response = upload(client, meeting_id, uuid.uuid4())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_LIMIT"
    assert client.get(f"/v1/meetings/{meeting_id}").json()["meeting"]["status"] == "draft"


def test_storage_failure_keeps_meeting_retryable(api_client, monkeypatch):
    client, _ = api_client
    storage = FakeStorage()
    storage.fail = True
    app.dependency_overrides[get_storage] = lambda: storage
    monkeypatch.setattr(meetings, "inspect_audio", lambda path, mime: ("audio/ogg", 2000))
    meeting_id = create_meeting(client)
    response = upload(client, meeting_id, uuid.uuid4())
    assert response.status_code == 503
    assert client.get(f"/v1/meetings/{meeting_id}").json()["meeting"]["status"] == "draft"


def test_request_body_is_rejected_before_multipart_spooling(api_client, monkeypatch):
    client, _ = api_client
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    monkeypatch.setattr("app.size_limit.MAX_UPLOAD_REQUEST_BYTES", 100)
    meeting_id = create_meeting(client)
    response = upload(client, meeting_id, uuid.uuid4(), data=b"OggS" + b"x" * 200)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert storage.uploaded == []
