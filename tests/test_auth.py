from fastapi.testclient import TestClient

from courtside.db.models import User


def test_login_with_valid_credentials(client: TestClient, user: User) -> None:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "token" in body and isinstance(body["token"], str)
    assert body["player"]["jerseyNumber"] == 10
    assert body["player"]["position"] == "Guard"
    assert body["player"]["onboardedAt"] is None


def test_login_bad_password(client: TestClient, user: User) -> None:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "wrong"},
    )
    assert r.status_code == 401
    assert r.json() == {
        "error": "invalid_credentials",
        "message": "Email or password incorrect",
    }


def test_login_unknown_email(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "x"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


def test_login_invalid_email_format(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_logout_returns_empty(client: TestClient) -> None:
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {}
