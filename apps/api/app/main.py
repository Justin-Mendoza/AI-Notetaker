import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.meetings import router as meetings_router
from app.db.session import engine
from app.errors import ApiError, api_error_handler, error_response, validation_error_handler
from app.settings import settings

app = FastAPI(title="Meeting Notes API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_web_origin],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.add_exception_handler(ApiError, api_error_handler)
from fastapi.exceptions import RequestValidationError  # noqa: E402

app.add_exception_handler(RequestValidationError, validation_error_handler)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        response = error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")
    response.headers["X-Request-ID"] = request.state.request_id
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


app.include_router(meetings_router)
