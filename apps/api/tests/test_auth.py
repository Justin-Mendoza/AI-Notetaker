from fastapi.testclient import TestClient

from app.auth.local import get_current_user
from app.main import app


def local_client(**kwargs):
    return TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
        **kwargs,
    )


def test_local_browser_uses_single_owner(api_client):
    app.dependency_overrides.pop(get_current_user)
    with local_client() as client:
        created = client.post(
            "/v1/meetings",
            json={"consent_confirmed": True, "consent_policy_version": "v1"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert created.status_code == 201
        assert len(client.get("/v1/meetings").json()["items"]) == 1


def test_rejects_network_client(api_client):
    app.dependency_overrides.pop(get_current_user)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.10", 50000)) as client:
        response = client.get("/v1/meetings")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_ONLY"


def test_rejects_dns_rebinding_host(api_client):
    app.dependency_overrides.pop(get_current_user)
    with TestClient(
        app, base_url="http://attacker.example:8000", client=("127.0.0.1", 50000)
    ) as client:
        response = client.get("/v1/meetings")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_ONLY"


def test_rejects_cross_site_write_and_missing_origin(api_client):
    app.dependency_overrides.pop(get_current_user)
    body = {"consent_confirmed": True, "consent_policy_version": "v1"}
    with local_client() as client:
        cross_site = client.post(
            "/v1/meetings", json=body, headers={"Origin": "https://attacker.example"}
        )
        missing_origin = client.post("/v1/meetings", json=body)
    assert cross_site.status_code == 403
    assert cross_site.json()["error"]["code"] == "ORIGIN_DENIED"
    assert missing_origin.status_code == 403
    assert missing_origin.json()["error"]["code"] == "ORIGIN_REQUIRED"
