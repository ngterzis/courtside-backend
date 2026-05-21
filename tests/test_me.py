from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from courtside.db.models import Player, User


def _login(client: TestClient) -> str:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_me_without_token(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json() == {
        "error": "unauthorized",
        "message": "Missing or invalid token",
    }


def test_me_with_invalid_token(client: TestClient) -> None:
    r = client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_me_with_valid_token(client: TestClient, user: User) -> None:
    token = _login(client)
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["jerseyNumber"] == 10
    assert body["position"] == "Guard"
    assert body["onboardedAt"] is None


def test_onboard_sets_jersey_position_and_timestamp(
    client: TestClient, user: User, player: Player, db: Session
) -> None:
    token = _login(client)
    r = client.post(
        "/api/me/onboard",
        json={"jerseyNumber": 23, "position": "Forward"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jerseyNumber"] == 23
    assert body["position"] == "Forward"
    assert body["onboardedAt"] is not None

    db.refresh(player)
    assert player.jersey_number == 23
    assert player.onboarded_at is not None


def test_onboard_requires_auth(client: TestClient) -> None:
    r = client.post("/api/me/onboard", json={"jerseyNumber": 1, "position": "Guard"})
    assert r.status_code == 401
