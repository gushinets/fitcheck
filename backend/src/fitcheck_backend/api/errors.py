from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from fitcheck_backend.auth.errors import AuthError


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: list[str | int]
    code: str


class ErrorBody(BaseModel):
    code: str
    message: str
    requestId: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str, request_id: str,
                   details: list[ErrorDetail] | None = None, headers: dict | None = None) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, requestId=request_id,
                                        details=details or []))
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError):
        headers = {'Retry-After': str(exc.retry_after)} if exc.retry_after is not None else None
        return error_response(exc.status, exc.code, exc.code.replace('_', ' ').capitalize(), request.state.request_id, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        details = [ErrorDetail(location=list(item["loc"]), code=item["type"]) for item in exc.errors()]
        return error_response(400, "invalid_request", "Invalid request", request.state.request_id, details)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {400: "invalid_request", 401: "unauthenticated", 403: "forbidden",
                 404: "not_found", 405: "method_not_allowed", 409: "conflict",
                 413: "body_too_large", 415: "unsupported_content_type", 429: "rate_limited",
                 502: "upstream_failure", 503: "service_unavailable", 504: "timeout"}
        code = codes.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, code.replace("_", " ").capitalize(),
                              request.state.request_id, headers=exc.headers)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message, request.state.request_id)
