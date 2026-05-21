from fastapi.testclient import TestClient

from courtside.db.models import Season, User


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_list_seasons_returns_newest_first(
    client: TestClient,
    user: User,
    current_season: Season,
    previous_season: Season,
) -> None:
    r = client.get("/api/seasons", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["label"] == current_season.label
    assert body[1]["label"] == previous_season.label
    assert body[0]["endDate"] is None
    assert body[1]["endDate"] is not None


def test_current_season(
    client: TestClient,
    user: User,
    current_season: Season,
    previous_season: Season,
) -> None:
    r = client.get("/api/seasons/current", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == current_season.label
    assert body["endDate"] is None


def test_current_season_404_when_none_active(
    client: TestClient,
    user: User,
    previous_season: Season,
) -> None:
    r = client.get("/api/seasons/current", headers=_login(client))
    assert r.status_code == 404
    assert r.json()["error"] == "no_active_season"


def test_seasons_require_auth(client: TestClient) -> None:
    assert client.get("/api/seasons").status_code == 401
    assert client.get("/api/seasons/current").status_code == 401
