import json
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from courtside.db.models import CoachNote, Game, HomeAway, Player, Result, Season, Team
from courtside.services.chat_tools import execute_tool, status_for, tool_definitions


def _run(db: Session, player: Player, name: str, args: dict[str, Any] | None = None):
    outcome = execute_tool(name, args or {}, db, player)
    return json.loads(outcome.content), outcome.is_error


def _game(
    team: Team,
    player: Player,
    season: Season,
    day: date,
    *,
    opponent: str = "Rivals",
    home_away: HomeAway = HomeAway.HOME,
    result: Result = Result.WIN,
    points: int = 20,
) -> Game:
    return Game(
        team_id=team.id,
        player_id=player.id,
        season_id=season.id,
        date=day,
        opponent=opponent,
        home_away=home_away,
        result=result,
        team_score=80,
        opponent_score=70,
        points=points,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=0,
        turnovers=2,
        fouls=2,
        fg2_made=8,
        fg2_attempted=16,
        three_made=1,
        three_attempted=4,
        ft_made=1,
        ft_attempted=2,
    )


@pytest.fixture
def varied_games(
    db: Session, team: Team, player: Player, current_season: Season
) -> list[Game]:
    base = date(2026, 3, 7)
    games = [
        _game(team, player, current_season, base, opponent="Hawks", points=12),
        _game(
            team,
            player,
            current_season,
            base + timedelta(weeks=1),
            opponent="Bulls",
            home_away=HomeAway.AWAY,
            result=Result.LOSS,
            points=31,
        ),
        _game(
            team,
            player,
            current_season,
            base + timedelta(weeks=5),
            opponent="Night Hawks",
            home_away=HomeAway.AWAY,
            points=18,
        ),
    ]
    db.add_all(games)
    db.flush()
    return games


def test_tool_definitions_are_stable_and_schema_only() -> None:
    defs = tool_definitions()
    assert [d["name"] for d in defs] == [
        "list_seasons",
        "get_season_summary",
        "find_games",
        "get_game",
        "get_split_averages",
    ]
    assert defs == tool_definitions()
    for d in defs:
        assert d["input_schema"]["type"] == "object"
        assert "player_id" not in json.dumps(d)
        assert '"title"' not in json.dumps(d)


def test_find_games_sorts_filters_and_truncates(
    db: Session, player: Player, varied_games: list[Game]
) -> None:
    out, err = _run(db, player, "find_games", {"sort_by": "points", "limit": 2})
    assert not err
    assert [g["points"] for g in out["games"]] == [31, 18]
    assert out["total_matched"] == 3
    assert out["truncated"] is True

    out, _ = _run(db, player, "find_games", {"opponent": "hawks"})
    assert {g["opponent"] for g in out["games"]} == {"Hawks", "Night Hawks"}

    out, _ = _run(db, player, "find_games", {"result": "L"})
    assert [g["opponent"] for g in out["games"]] == ["Bulls"]

    out, _ = _run(
        db, player, "find_games", {"date_from": "2026-03-10", "home_away": "A"}
    )
    assert [g["opponent"] for g in out["games"]] == ["Night Hawks", "Bulls"]


def test_find_games_rejects_bad_arguments(
    db: Session, player: Player, varied_games: list[Game]
) -> None:
    out, err = _run(db, player, "find_games", {"limit": 500, "player_id": "x"})
    assert err
    fields = {d["field"] for d in out["details"]}
    assert {"limit", "player_id"} <= fields


def test_get_game_by_id_and_date_with_coach_note(
    db: Session, team: Team, player: Player, varied_games: list[Game]
) -> None:
    best = varied_games[1]
    db.add(CoachNote(team_id=team.id, game_id=best.id, author_name="Coach K", text="Huge."))
    db.flush()

    out, err = _run(db, player, "get_game", {"game_id": str(best.id)})
    assert not err
    assert out["points"] == 31
    assert out["coach_note"] == {"author": "Coach K", "text": "Huge."}
    assert "points" in out["season_highs_set"]

    out, err = _run(db, player, "get_game", {"date": best.date.isoformat()})
    assert not err and out["game_id"] == str(best.id)

    out, err = _run(db, player, "get_game", {})
    assert err


def test_split_averages(db: Session, player: Player, varied_games: list[Game]) -> None:
    out, err = _run(db, player, "get_split_averages", {"group_by": "home_away"})
    assert not err
    groups = {g["group"]: g for g in out["groups"]}
    assert groups["home"]["games"] == 1
    assert groups["away"]["averages"]["points"] == 24.5
    assert out["overall"]["points"] == pytest.approx(20.3)
    # Percentages are on a 0-100 scale for the model.
    assert groups["home"]["averages"]["fg_pct"] == 50.0

    out, _ = _run(
        db, player, "get_split_averages", {"group_by": "result", "last_n_games": 1}
    )
    assert out["games_considered"] == 1
    assert [g["group"] for g in out["groups"]] == ["wins"]


def test_seasons_and_summaries(
    db: Session,
    team: Team,
    player: Player,
    current_season: Season,
    previous_season: Season,
    varied_games: list[Game],
) -> None:
    db.add(_game(team, player, previous_season, date(2025, 10, 1), points=40))
    db.flush()

    out, _ = _run(db, player, "list_seasons")
    by_label = {s["label"]: s for s in out["seasons"]}
    assert by_label["Spring '26"]["is_active"] is True
    assert by_label["Spring '26"]["games_played"] == 3
    assert by_label["Fall '25"]["games_played"] == 1

    out, _ = _run(db, player, "get_season_summary")
    assert out["season"] == "Spring '26"
    assert out["record"] == {"wins": 2, "losses": 1}
    assert out["totals"]["points"] == 61

    out, _ = _run(
        db, player, "get_season_summary", {"season_id": str(previous_season.id)}
    )
    assert out["averages"]["points"] == 40.0

    out, _ = _run(db, player, "find_games", {"season_id": "all", "sort_by": "points"})
    assert out["games"][0]["points"] == 40


def test_tools_never_return_teammate_data(
    db: Session,
    team: Team,
    player: Player,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    own_ids = {str(g.id) for g in main_games}
    out, _ = _run(db, player, "find_games", {"season_id": "all", "limit": 25})
    assert {g["game_id"] for g in out["games"]} == own_ids

    # A teammate's game id is "not found", not their box score.
    out, err = _run(db, player, "get_game", {"game_id": str(teammate_games[0].id)})
    assert err and "No game found" in out["error"]

    for name in ("list_seasons", "get_season_summary", "find_games"):
        blob, _ = _run(db, player, name)
        for mate in teammates:
            assert mate.name not in json.dumps(blob)
    blob, _ = _run(db, player, "get_split_averages", {"group_by": "opponent"})
    assert blob["games_considered"] == len(main_games)


def test_season_from_another_team_is_rejected(
    db: Session, player: Player, current_season: Season
) -> None:
    other_team = Team(name="Other")
    db.add(other_team)
    db.flush()
    foreign = Season(team_id=other_team.id, label="X", start_date=date(2026, 1, 1))
    db.add(foreign)
    db.flush()
    out, err = _run(db, player, "get_season_summary", {"season_id": str(foreign.id)})
    assert err and "not found" in out["error"]


def test_unknown_tool_and_status_labels(db: Session, player: Player) -> None:
    out, err = _run(db, player, "drop_tables")
    assert err
    assert status_for(["find_games"]) == "Looking up your games…"
    assert status_for(["find_games", "get_game"]) == "Looking things up…"
