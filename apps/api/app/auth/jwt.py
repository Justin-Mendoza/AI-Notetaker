import uuid
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.errors import ApiError
from app.settings import settings

bearer = HTTPBearer(auto_error=False)


class TokenVerifier:
    def __init__(self, jwks_client: PyJWKClient, issuer: str, audience: str):
        self.jwks_client = jwks_client
        self.issuer = issuer
        self.audience = audience

    def verify(self, token: str) -> uuid.UUID:
        try:
            key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            if claims.get("role") != "authenticated":
                raise ValueError("not an authenticated user token")
            return uuid.UUID(claims["sub"])
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise ApiError(401, "INVALID_TOKEN", "A valid sign-in token is required") from exc


@lru_cache
def get_verifier() -> TokenVerifier:
    try:
        settings.validate_auth()
    except ValueError as exc:
        raise ApiError(503, "AUTH_UNAVAILABLE", "Authentication is not configured") from exc
    client = PyJWKClient(settings.jwks_url, cache_jwk_set=True, lifespan=300, timeout=5)
    return TokenVerifier(client, settings.issuer, settings.supabase_jwt_audience)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> uuid.UUID:
    if credentials is None:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in to continue")
    return get_verifier().verify(credentials.credentials)
