from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from courtside.db.models import Game, Player, Season, User


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_archetype_404_when_no_games(
    client: TestClient, user: User, current_season: Season
) -> None:
    r = client.get("/api/me/archetype", headers=_login(client))
    assert r.status_code == 404
    assert r.json()["error"] == "insufficient_games"


def test_archetype_404_when_fewer_than_three_games(
    client: TestClient,
    user: User,
    current_season: Season,
    team,
    player: Player,
    db: Session,
) -> None:
    from datetime import date

    from courtside.db.models import HomeAway, Result

    for i in range(2):
        db.add(
            Game(
                team_id=team.id,
                player_id=player.id,
                season_id=current_season.id,
                date=date(2026, 3, 7 + i * 7),
                opponent="X",
                home_away=HomeAway.HOME,
                result=Result.WIN,
                team_score=80,
                opponent_score=70,
                points=10,
                rebounds=4,
                assists=3,
                steals=1,
                blocks=0,
                turnovers=2,
                fouls=2,
                fg_made=4,
                fg_attempted=10,
                three_made=1,
                three_attempted=3,
                ft_made=1,
                ft_attempted=2,
            )
        )
    db.flush()

    r = client.get("/api/me/archetype", headers=_login(client))
    assert r.status_code == 404
    assert r.json()["error"] == "insufficient_games"


def test_archetype_returns_primary_secondary_and_receipt(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    with patch(
        "courtside.routes.archetype.generate_archetype_explanation",
        return_value="Stub explanation.",
    ) as gen:
        r = client.get("/api/me/archetype", headers=_login(client))

    assert r.status_code == 200
    body = r.json()
    assert body["primary"] in {
        "Playmaker",
        "Efficient Scorer",
        "Glass Cleaner",
        "Defensive Anchor",
        "3&D Wing",
        "Rim Protector",
        "Spark Plug",
        "Floor General",
        "Hustle Player",
    }
    assert body["secondary"] != body["primary"]
    assert body["explanation"] == "Stub explanation."
    assert 3 <= len(body["receipt"]) <= 5
    assert {"stat", "value", "percentile", "comment"} <= set(body["receipt"][0].keys())
    assert body["scores"] is not None
    assert len(body["scores"]) == 9
    assert sorted(s["score"] for s in body["scores"]) == [
        s["score"] for s in sorted(body["scores"], key=lambda s: s["score"])
    ]
    primary_marks = [s for s in body["scores"] if s.get("isPrimary")]
    secondary_marks = [s for s in body["scores"] if s.get("isSecondary")]
    assert len(primary_marks) == 1
    assert len(secondary_marks) == 1
    assert primary_marks[0]["name"] == body["primary"]
    gen.assert_called_once()


def test_archetype_cached_on_second_call(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    with patch(
        "courtside.routes.archetype.generate_archetype_explanation",
        return_value="First.",
    ):
        first = client.get("/api/me/archetype", headers=_login(client))
    assert first.status_code == 200
    assert first.json()["explanation"] == "First."

    with patch(
        "courtside.routes.archetype.generate_archetype_explanation",
        return_value="Second.",
    ) as gen:
        second = client.get("/api/me/archetype", headers=_login(client))
        gen.assert_not_called()
    assert second.json()["explanation"] == "First."


def test_archetype_history_returns_one_per_season(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    with patch(
        "courtside.routes.archetype.generate_archetype_explanation",
        return_value="X.",
    ):
        client.get("/api/me/archetype", headers=_login(client))

    r = client.get("/api/me/archetype/history", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["seasonId"] == str(current_season.id)


def test_archetype_requires_auth(client: TestClient) -> None:
    assert client.get("/api/me/archetype").status_code == 401
    assert client.get("/api/me/archetype/history").status_code == 401
