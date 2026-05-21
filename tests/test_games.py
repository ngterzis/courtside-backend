from fastapi.testclient import TestClient

from courtside.db.models import CoachNote, Game, Player, Season, User


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_list_my_games_defaults_to_current_season(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get("/api/me/games", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["games"]) == 3
    dates = [g["date"] for g in body["games"]]
    assert dates == sorted(dates, reverse=True)


def test_list_games_pagination(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get(
        "/api/me/games?limit=1&offset=1", headers=_login(client)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["games"]) == 1


def test_game_response_shape(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get("/api/me/games", headers=_login(client))
    g = r.json()["games"][0]
    assert {"id", "seasonId", "date", "opponent", "homeAway", "result",
            "teamScore", "opponentScore", "stats", "personalBests"}.issubset(g)
    stats = g["stats"]
    assert {"points", "rebounds", "assists", "fgPct", "threePct", "ftPct",
            "tsPct"}.issubset(stats)


def test_personal_bests_marks_top_game(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get("/api/me/games", headers=_login(client))
    games = r.json()["games"]
    # main_games has points 18, 20, 22 → newest (22) is top
    newest = games[0]
    assert "points" in newest["personalBests"]
    assert "assists" in newest["personalBests"]


def test_last_game_returns_most_recent(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get("/api/me/games/last", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["stats"]["points"] == 22


def test_last_game_returns_null_when_no_games(
    client: TestClient,
    user: User,
    current_season: Season,
) -> None:
    r = client.get("/api/me/games/last", headers=_login(client))
    assert r.status_code == 200
    assert r.json() is None


def test_get_game_by_id(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    target = main_games[0]
    r = client.get(f"/api/games/{target.id}", headers=_login(client))
    assert r.status_code == 200
    assert r.json()["id"] == str(target.id)


def test_get_game_404_when_other_player(
    client: TestClient,
    user: User,
    current_season: Season,
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    foreign_game = teammate_games[0]
    r = client.get(f"/api/games/{foreign_game.id}", headers=_login(client))
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_game_includes_coach_note(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    db,
    team,
) -> None:
    note = CoachNote(
        team_id=team.id,
        game_id=main_games[-1].id,
        author_name="Coach",
        text="Nice work tonight.",
    )
    db.add(note)
    db.flush()

    r = client.get(f"/api/games/{main_games[-1].id}", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body["coachNote"]["authorName"] == "Coach"
    assert body["coachNote"]["text"] == "Nice work tonight."
