from fastapi import FastAPI
from fastapi.testclient import TestClient

from courtside.origin import OriginVerifyMiddleware


def _client(secret: str | None) -> TestClient:
    app = FastAPI()
    app.add_middleware(OriginVerifyMiddleware, secret=secret)

    @app.get("/api/games")
    def games() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_allows_requests_carrying_the_secret() -> None:
    r = _client("s3cret").get("/api/games", headers={"X-Origin-Verify": "s3cret"})
    assert r.status_code == 200


def test_rejects_requests_without_the_secret() -> None:
    r = _client("s3cret").get("/api/games")
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_rejects_requests_with_the_wrong_secret() -> None:
    r = _client("s3cret").get("/api/games", headers={"X-Origin-Verify": "nope"})
    assert r.status_code == 403


def test_health_is_exempt_so_deploys_can_probe_the_origins() -> None:
    assert _client("s3cret").get("/api/health").status_code == 200


def test_no_secret_configured_disables_the_check() -> None:
    assert _client(None).get("/api/games").status_code == 200
