import base64
import json
import uuid


def test_meeting_create_list_and_owner_isolation(api_client):
    client, identity = api_client
    denied = client.post(
        "/v1/meetings",
        json={"title": "Planning", "consent_confirmed": False, "consent_policy_version": "v1"},
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "INVALID_INPUT"

    created = client.post(
        "/v1/meetings",
        json={"title": "  Planning  ", "consent_confirmed": True, "consent_policy_version": "v1"},
    )
    assert created.status_code == 201
    meeting_id = created.json()["meeting"]["id"]
    assert created.json()["meeting"]["title"] == "Planning"
    assert len(client.get("/v1/meetings").json()["items"]) == 1
    assert client.get(f"/v1/meetings/{meeting_id}").status_code == 200

    identity["owner"] = uuid.uuid4()
    assert client.get("/v1/meetings").json()["items"] == []
    assert client.get(f"/v1/meetings/{meeting_id}").status_code == 404
    assert client.patch(f"/v1/meetings/{meeting_id}", json={"title": "Stolen"}).status_code == 404


def test_title_validation_and_rename(api_client):
    client, _ = api_client
    response = client.post(
        "/v1/meetings", json={"consent_confirmed": True, "consent_policy_version": "v1"}
    )
    meeting_id = response.json()["meeting"]["id"]
    assert response.json()["meeting"]["title"] == "Untitled class"
    assert client.patch(f"/v1/meetings/{meeting_id}", json={"title": "  "}).status_code == 422
    renamed = client.patch(f"/v1/meetings/{meeting_id}", json={"title": " New title "})
    assert renamed.status_code == 200
    assert renamed.json()["meeting"]["title"] == "New title"


def test_creation_rate_limit_is_per_owner(api_client):
    client, identity = api_client
    body = {"consent_confirmed": True, "consent_policy_version": "v1"}
    for _ in range(20):
        assert client.post("/v1/meetings", json=body).status_code == 201
    limited = client.post("/v1/meetings", json=body)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    identity["owner"] = uuid.uuid4()
    assert client.post("/v1/meetings", json=body).status_code == 201


def test_cursor_pagination_and_invalid_timezone(api_client):
    client, _ = api_client
    body = {"consent_confirmed": True, "consent_policy_version": "v1"}
    ids = [client.post("/v1/meetings", json=body).json()["meeting"]["id"] for _ in range(3)]
    first = client.get("/v1/meetings", params={"limit": 2}).json()
    assert [item["id"] for item in first["items"]] == ids[::-1][:2]
    second = client.get("/v1/meetings", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [item["id"] for item in second["items"]] == [ids[0]]
    naive = base64.urlsafe_b64encode(
        json.dumps(["2026-09-30T12:00:00", str(uuid.uuid4())]).encode()
    ).decode()
    response = client.get("/v1/meetings", params={"cursor": naive})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CURSOR"
