"""Bound the multipart request before FastAPI spools it to disk."""

from app.services.media import MAX_FILE_BYTES

MAX_UPLOAD_REQUEST_BYTES = MAX_FILE_BYTES + 1_000_000


class UploadTooLarge(Exception):
    pass


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].endswith("/recording"):
            await self.app(scope, receive, send)
            return
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    if int(value) > MAX_UPLOAD_REQUEST_BYTES:
                        raise UploadTooLarge()
                except ValueError:
                    raise UploadTooLarge() from None
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_UPLOAD_REQUEST_BYTES:
                    raise UploadTooLarge()
            return message

        await self.app(scope, bounded_receive, send)
