import ipaddress
import uuid
from urllib.parse import urlparse

from fastapi import Request

from app.errors import ApiError
from app.settings import settings

# A stable owner keeps existing rows scoped even without an account service.
LOCAL_OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def get_current_user(request: Request) -> uuid.UUID:
    """Permit only this Mac's browser to use the single-owner API."""
    client_host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(client_host).is_loopback:
            raise ValueError("non-loopback client")
    except ValueError as exc:
        raise ApiError(403, "LOCAL_ONLY", "Open the app on this Mac") from exc

    if request.url.hostname not in LOCAL_HOSTS:
        raise ApiError(403, "LOCAL_ONLY", "Open the app on this Mac")

    web_origin = urlparse(settings.allowed_web_origin)
    if web_origin.scheme != "http" or web_origin.hostname not in LOCAL_HOSTS:
        raise ApiError(503, "LOCAL_ORIGIN_INVALID", "Local web origin is not configured")

    origin = request.headers.get("origin")
    if origin is not None and origin != settings.allowed_web_origin:
        raise ApiError(403, "ORIGIN_DENIED", "Request origin is not allowed")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is None:
        raise ApiError(403, "ORIGIN_REQUIRED", "Local web origin is required")

    return LOCAL_OWNER_ID
