import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.jwt import TokenVerifier, get_current_user
from app.errors import ApiError
from app.main import app


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwksClient:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return FakeSigningKey(self.key)


@pytest.fixture
def signed_token():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    owner = uuid.uuid4()
    now = datetime.now(UTC)
    claims = {
        "sub": str(owner),
        "iss": "https://test.supabase.co/auth/v1",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    verifier = TokenVerifier(
        FakeJwksClient(private_key.public_key()),
        "https://test.supabase.co/auth/v1",
        "authenticated",
    )
    return private_key, claims, verifier, owner


def test_valid_token(signed_token):
    key, claims, verifier, owner = signed_token
    assert verifier.verify(jwt.encode(claims, key, algorithm="RS256")) == owner


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://elsewhere.invalid/auth/v1"},
        {"aud": "other"},
        {"role": "anon"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"sub": "not-a-uuid"},
    ],
)
def test_rejects_invalid_claims(signed_token, change):
    key, claims, verifier, _ = signed_token
    with pytest.raises(ApiError) as error:
        verifier.verify(jwt.encode(claims | change, key, algorithm="RS256"))
    assert error.value.status_code == 401


def test_rejects_wrong_signature(signed_token):
    _, claims, verifier, _ = signed_token
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ApiError):
        verifier.verify(jwt.encode(claims, other_key, algorithm="RS256"))


def test_missing_token_uses_error_shape():
    with TestClient(app) as client:
        response = client.get("/v1/meetings")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_authenticated_http_request_uses_verified_subject(api_client, signed_token, monkeypatch):
    client, _ = api_client
    key, claims, verifier, _ = signed_token
    app.dependency_overrides.pop(get_current_user)
    monkeypatch.setattr("app.auth.jwt.get_verifier", lambda: verifier)
    token = jwt.encode(claims, key, algorithm="RS256")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/v1/meetings",
        json={"consent_confirmed": True, "consent_policy_version": "v1"},
        headers=headers,
    )
    assert created.status_code == 201
    assert len(client.get("/v1/meetings", headers=headers).json()["items"]) == 1

    other_claims = claims | {"sub": str(uuid.uuid4())}
    other_headers = {"Authorization": f"Bearer {jwt.encode(other_claims, key, algorithm='RS256')}"}
    assert client.get("/v1/meetings", headers=other_headers).json()["items"] == []
    meeting_id = created.json()["meeting"]["id"]
    assert client.get(f"/v1/meetings/{meeting_id}", headers=other_headers).status_code == 404
    assert client.get(f"/v1/meetings/{meeting_id}", headers=headers).status_code == 200
