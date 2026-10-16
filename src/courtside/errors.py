import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import StatementError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    500: "internal_error",
    503: "service_unavailable",
}

# Seconds the client should wait before retrying while Aurora resumes.
_RESUME_RETRY_AFTER = 5


def _is_database_resuming(exc: BaseException) -> bool:
    """True when Aurora rejected the call because it is waking from auto-pause.

    The Data API raises a botocore ClientError with this code, which SQLAlchemy
    wraps (as `orig`) in a StatementError. Matching on the code avoids importing
    botocore's dynamically generated exception classes.
    """
    seen: set[int] = set()
    pending: list[BaseException | None] = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        response = getattr(current, "response", None)
        if isinstance(response, dict):
            code = response.get("Error", {}).get("Code")
            if code == "DatabaseResumingException":
                return True
        pending.extend(
            [getattr(current, "orig", None), current.__cause__, current.__context__]
        )
    return False


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "message": exc.message},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": _STATUS_CODES.get(exc.status_code, "http_error"),
                "message": str(exc.detail) if exc.detail else "",
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "error": "validation_error",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                }
            ),
        )

    @app.exception_handler(StatementError)
    async def statement_error_handler(
        _: Request, exc: StatementError
    ) -> JSONResponse:
        if not _is_database_resuming(exc):
            # Unchanged behaviour for real failures: ServerErrorMiddleware logs
            # the traceback and returns a 500.
            raise exc
        logger.info("Aurora is resuming from auto-pause; asking the client to retry")
        return JSONResponse(
            status_code=503,
            content={
                "error": "database_resuming",
                "message": (
                    "The database is resuming after being paused. "
                    "Retry in a few seconds."
                ),
            },
            headers={"Retry-After": str(_RESUME_RETRY_AFTER)},
        )
