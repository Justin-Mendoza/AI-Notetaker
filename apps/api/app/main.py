import hmac
import logging
import time
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text

from app.api.meetings import router as meetings_router
from app.auth.local import local_web_origins
from app.db.session import SessionLocal, engine
from app.errors import ApiError, api_error_handler, error_response, validation_error_handler
from app.models.job import ProcessingJob
from app.models.meeting import utc_now
from app.models.recording import Recording
from app.observability import configure_logging
from app.settings import settings
from app.size_limit import UploadLimitMiddleware, UploadTooLarge

app = FastAPI(title="Meeting Notes API", version="0.1.0")
configure_logging()
logger = logging.getLogger(__name__)
app.add_middleware(UploadLimitMiddleware)
app.add_exception_handler(ApiError, api_error_handler)
from fastapi.exceptions import RequestValidationError  # noqa: E402

app.add_exception_handler(RequestValidationError, validation_error_handler)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    started = time.monotonic()
    try:
        response = await call_next(request)
    except UploadTooLarge:
        response = error_response(
            request, 413, "REQUEST_TOO_LARGE", "Recording upload is too large"
        )
    except Exception:
        response = error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "http_request",
        extra={
            "request_id": request.state.request_id,
            "status_code": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return response


@app.get("/healthz", tags=["infrastructure"])
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", tags=["infrastructure"])
def readyz() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "Database is unavailable") from exc
    return {"status": "ready"}


@app.get("/internal/metrics", include_in_schema=False)
def metrics(authorization: str | None = Header(default=None)) -> PlainTextResponse:
    if not settings.metrics_token:
        raise ApiError(404, "NOT_FOUND", "Not found")
    if authorization is None or not hmac.compare_digest(
        authorization, f"Bearer {settings.metrics_token}"
    ):
        raise ApiError(401, "UNAUTHORIZED", "Authentication required")
    with SessionLocal() as db:
        counts = dict(
            db.execute(
                select(ProcessingJob.status, func.count(ProcessingJob.id)).group_by(
                    ProcessingJob.status
                )
            )
        )
        overdue_audio = db.scalar(
            select(func.count(Recording.id)).where(
                Recording.purge_after < utc_now(), Recording.deleted_at.is_(None)
            )
        )
    lines = [
        "# TYPE meeting_jobs gauge",
        *(
            f'meeting_jobs{{status="{status}"}} {counts.get(status, 0)}'
            for status in ("pending", "running", "failed", "completed")
        ),
        "# TYPE meeting_overdue_audio gauge",
        f"meeting_overdue_audio {overdue_audio}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


app.include_router(meetings_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(local_web_origins()),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
