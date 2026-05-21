from fastapi.testclient import TestClient

from courtside.main import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env"] == "local"
