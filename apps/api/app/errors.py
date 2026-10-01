import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return error_response(request, error.status_code, error.code, error.message)


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, "INVALID_INPUT", "Check the request fields and try again")
