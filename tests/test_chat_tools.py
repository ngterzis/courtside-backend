import json
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from courtside.db.models import (
    CoachNote,
    GamePerformance,
    HomeAway,
    Player,
    Result,
    Season,
    Team,
)
from courtside.services.chat_tools import execute_tool, status_for, tool_definitions
from tests.factories import add_performance


def _run(db: Session, player: Player, name: str, args: dict[str, Any] | None = None):
    outcome = execute_tool(name, args or {}, db, player)
    return json.loads(outcome.content), outcome.is_error


def _game(
    db: Session,
    player: Player,
    season: Season,
    day: date,
    *,
    opponent: str = "Rivals",
    home_away: HomeAway = HomeAway.HOME,
    result: Result = Result.WIN,
    points: int = 20,
) -> GamePerformance:
    return add_performance(
        db,
        player,
        season,
        day,
        opponent=opponent,
        home_away=home_away,
        result=result,
        points=points,
        three_made=1,
        three_attempted=4,
        ft_made=1,
        ft_attempted=2,
    )


@pytest.fixture
def varied_games(
    db: Session, player: Player, current_season: Season
) -> list[GamePerformance]:
    base = date(2026, 3, 7)
    return [
        _game(db, player, current_season, base, opponent="Hawks", points=12),
        _game(
            db,
            player,
            current_season,
            base + timedelta(weeks=1),
            opponent="Bulls",
            home_away=HomeAway.AWAY,
            result=Result.LOSS,
            points=31,
        ),
        _game(
            db,
            player,
            current_season,
            base + timedelta(weeks=5),
            opponent="Night Hawks",
            home_away=HomeAway.AWAY,
            points=18,
        ),
    ]


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
    db: Session, player: Player, varied_games: list[GamePerformance]
) -> None:
    out, err = _run(db, player, "find_games", {"sort_by": "points", "limit": 2})
    assert not err
    assert [g["points"] for g in out["games"]] == [31, 18]
    assert out["total_matched"] == 3
    assert out["truncated"] is True

    out, _ = _run(db, player, "find_games", {"opponent": "hawks"})
    assert {g["opponent"] for g in out["games"]} == {"Hawks", "Night Hawks"}

    # Rows carry makes and attempts, not only percentages.
    row = out["games"][0]
    assert (row["fg2_made"], row["fg2_attempted"]) == (8, 16)
    assert (row["three_attempted"], row["ft_attempted"]) == (4, 2)

    out, err = _run(db, player, "find_games", {"sort_by": "three_attempted"})
    assert not err
    # Totals combine two- and three-pointers (free throws excluded).
    assert (row["total_fg_made"], row["total_fg_attempted"]) == (9, 20)

    out, _ = _run(db, player, "find_games", {"result": "L"})
    assert [g["opponent"] for g in out["games"]] == ["Bulls"]

    out, _ = _run(
        db, player, "find_games", {"date_from": "2026-03-10", "home_away": "A"}
    )
    assert [g["opponent"] for g in out["games"]] == ["Night Hawks", "Bulls"]


def test_find_games_rejects_bad_arguments(
    db: Session, player: Player, varied_games: list[GamePerformance]
) -> None:
    out, err = _run(db, player, "find_games", {"limit": 500, "player_id": "x"})
    assert err
    fields = {d["field"] for d in out["details"]}
    assert {"limit", "player_id"} <= fields


def test_get_game_by_id_and_date_with_coach_note(
    db: Session, team: Team, player: Player, varied_games: list[GamePerformance]
) -> None:
    best = varied_games[1]
    db.add(
        CoachNote(team_id=team.id, performance_id=best.id, author_name="Coach K", text="Huge.")
    )
    db.flush()

    out, err = _run(db, player, "get_game", {"game_id": str(best.id)})
    assert not err
    assert out["points"] == 31
    assert out["coach_note"] == {"author": "Coach K", "text": "Huge."}
    assert "points" in out["season_highs_set"]

    out, err = _run(db, player, "get_game", {"date": best.game.date.isoformat()})
    assert not err and out["game_id"] == str(best.id)

    out, err = _run(db, player, "get_game", {})
    assert err


def test_split_averages(db: Session, player: Player, varied_games: list[GamePerformance]) -> None:
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
    varied_games: list[GamePerformance],
) -> None:
    _game(db, player, previous_season, date(2025, 10, 1), points=40)

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
    main_games: list[GamePerformance],
    teammates: list[Player],
    teammate_games: list[GamePerformance],
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


def test_find_games_sorts_by_total_field_goal_attempts(
    db: Session, team: Team, player: Player, current_season: Season
) -> None:
    # The most total attempts leads neither the 2PA nor the 3PA ranking.
    shapes = {"Inside": (24, 0), "Outside": (6, 12), "Balanced": (18, 9)}
    for i, (name, (fg2a, threea)) in enumerate(shapes.items()):
        g = _game(db, player, current_season, date(2026, 3, 7) + timedelta(days=i), opponent=name)
        g.fg2_attempted, g.three_attempted = fg2a, threea
    db.flush()

    out, _ = _run(db, player, "find_games", {"sort_by": "total_fg_attempted", "limit": 1})
    assert out["games"][0]["opponent"] == "Balanced"
    assert out["games"][0]["total_fg_attempted"] == 27

    out, _ = _run(db, player, "get_season_summary")
    assert out["averages"]["total_fg_attempted"] == 23.0
