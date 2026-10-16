from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import StatementError

from courtside.errors import install_error_handlers


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return app


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "..."}}, "BeginTransaction"
    )


def test_database_resuming_is_a_retryable_503() -> None:
    """Aurora auto-pause: the frontend shows a 'resuming' dialog and retries."""
    exc = StatementError(
        "(DatabaseResumingException)",
        None,
        None,
        orig=_client_error("DatabaseResumingException"),
    )

    r = TestClient(_app_raising(exc)).get("/boom")

    assert r.status_code == 503
    assert r.headers["Retry-After"] == "5"
    assert r.json()["error"] == "database_resuming"


def test_other_statement_errors_are_still_500() -> None:
    exc = StatementError(
        "(BadRequestException)", None, None, orig=_client_error("BadRequestException")
    )

    r = TestClient(_app_raising(exc), raise_server_exceptions=False).get("/boom")

    assert r.status_code == 500
