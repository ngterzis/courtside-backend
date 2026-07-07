from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Game, Prediction, Season, User


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_projection_requires_auth(client: TestClient) -> None:
    assert client.get("/api/me/projection").status_code == 401


def test_projection_falls_back_to_baseline(
    client: TestClient,
    db: Session,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    # main_games: three games scoring 18, 20, 22 → trailing-3 average = 20.0.
    r = client.get("/api/me/projection", headers=_login(client))
    assert r.status_code == 200
    body = r.json()

    assert body["source"] == "baseline"
    assert body["modelVersion"] == "baseline-trailing-avg"
    assert body["gamesConsidered"] == 3
    assert body["predictedPoints"] == 20.0
    assert body["baselinePoints"] == 20.0

    # The served projection is persisted for later monitoring.
    stored = db.scalars(select(Prediction)).all()
    assert len(stored) == 1
    assert stored[0].source == "baseline"
    assert stored[0].as_of_date == main_games[-1].date


def test_projection_with_no_games_is_zero(
    client: TestClient,
    user: User,
    current_season: Season,
) -> None:
    r = client.get("/api/me/projection", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body["gamesConsidered"] == 0
    assert body["predictedPoints"] == 0.0
