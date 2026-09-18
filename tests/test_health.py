from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from courtside.db.session import get_db
from courtside.main import app


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env"] == "local"
    assert body["error"] is None
    # create_all builds the test schema, so there is no alembic_version row.
    assert body["revision"] is None


def test_health_reports_alembic_revision(client: TestClient, db: Session) -> None:
    db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": "abc123"})

    r = client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["revision"] == "abc123"


def test_health_is_503_when_the_database_is_unreachable() -> None:
    """The signal deploy.yml rolls back on."""

    class BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def _override_get_db() -> Iterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["error"] == "OperationalError"
