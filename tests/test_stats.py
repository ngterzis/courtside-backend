from datetime import date

from fastapi.testclient import TestClient

from courtside.db.models import Game, HomeAway, Player, Result, Season, Team, User
from courtside.services.stats import (
    _label_for,
    _percentile_for_rank,
    derived_stats,
    personal_bests,
    season_averages,
)


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_derived_stats_handles_zero_attempts() -> None:
    g = _bare_game(fg_made=0, fg_attempted=0, three_made=0, three_attempted=0,
                   ft_made=0, ft_attempted=0, points=0)
    d = derived_stats(g)
    assert d == {"fg_pct": 0.0, "three_pct": 0.0, "ft_pct": 0.0, "ts_pct": 0.0}


def test_derived_stats_ts_pct_formula() -> None:
    g = _bare_game(points=20, fg_attempted=10, ft_attempted=4)
    d = derived_stats(g)
    expected_ts = 20 / (2 * (10 + 0.44 * 4))
    assert abs(d["ts_pct"] - expected_ts) < 1e-9


def test_personal_bests_excludes_zero_values() -> None:
    g1 = _bare_game(points=10, blocks=0)
    g2 = _bare_game(points=20, blocks=0)
    bests = personal_bests(g1, [g1, g2])
    assert "blocks" not in bests


def test_season_averages_aggregates_correctly() -> None:
    g1 = _bare_game(points=10, fg_made=4, fg_attempted=10)
    g2 = _bare_game(points=20, fg_made=8, fg_attempted=10)
    avg = season_averages([g1, g2], season_id=g1.season_id)
    assert avg["games_played"] == 2
    assert avg["points"] == 15.0
    assert avg["fg_pct"] == 12 / 20


def test_percentile_for_rank_endpoints() -> None:
    assert _percentile_for_rank(1, 5) == 100
    assert _percentile_for_rank(5, 5) == 0
    assert _percentile_for_rank(3, 5) == 50
    assert _percentile_for_rank(1, 1) == 100


def test_label_buckets() -> None:
    assert _label_for(100.0, 1) == "#1 on team"
    assert _label_for(90.0, 2) == "#2 on team"
    assert _label_for(80.0, 2) == "top 3"
    assert _label_for(60.0, 3) == "above avg"
    assert _label_for(40.0, 4) == "below avg"
    assert _label_for(10.0, 5) == "bottom 3"


def test_season_averages_endpoint(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    r = client.get("/api/me/season-averages", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert body["gamesPlayed"] == 3
    assert body["seasonId"] == str(current_season.id)
    assert body["points"] == (18 + 20 + 22) / 3
    assert "fgPct" in body
    assert "tsPct" in body


def test_team_ranks_endpoint(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    r = client.get("/api/me/team-ranks", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    stats = {row["stat"]: row for row in body}
    assert {"assists", "rebounds", "steals", "threePct"} == set(stats.keys())
    assert 0 <= stats["assists"]["percentile"] <= 100
    assert stats["assists"]["label"] in {
        "#1 on team",
        "#2 on team",
        "#3 on team",
        "#4 on team",
        "top 3",
        "above avg",
        "below avg",
        "bottom 3",
    }


def _bare_game(**overrides) -> Game:
    defaults = dict(
        team_id=Team(name="T").id,
        player_id=Player(team_id=Team(name="T").id, name="P", jersey_number=1, position="Guard").id,
        season_id=Season(team_id=Team(name="T").id, label="S", start_date=date(2026, 1, 1)).id,
        date=date(2026, 3, 1),
        opponent="X",
        home_away=HomeAway.HOME,
        result=Result.WIN,
        team_score=80,
        opponent_score=70,
        points=10,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=0,
        turnovers=2,
        fouls=2,
        fg_made=4,
        fg_attempted=10,
        three_made=2,
        three_attempted=5,
        ft_made=4,
        ft_attempted=5,
    )
    defaults.update(overrides)
    return Game(**defaults)
