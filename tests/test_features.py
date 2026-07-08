from datetime import date, timedelta
from uuid import uuid4

from courtside.db.models import Game, HomeAway, Result
from courtside.ml.features import (
    FEATURE_NAMES,
    MIN_HISTORY,
    build_training_examples,
    compute_features,
    to_vector,
)

_TEAM_ID = uuid4()
_SEASON_ID = uuid4()


def _game(*, day: int, points: int, home: bool = True, margin: int = 10) -> Game:
    return Game(
        team_id=_TEAM_ID,
        player_id=uuid4(),
        season_id=_SEASON_ID,
        date=date(2026, 3, 1) + timedelta(days=day),
        opponent="Rivals",
        home_away=HomeAway.HOME if home else HomeAway.AWAY,
        result=Result.WIN if margin > 0 else Result.LOSS,
        team_score=80,
        opponent_score=80 - margin,
        points=points,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=0,
        turnovers=2,
        fouls=2,
        fg_made=points // 3,
        fg_attempted=points // 2 or 1,
        three_made=1,
        three_attempted=3,
        ft_made=2,
        ft_attempted=2,
    )


def test_vector_matches_declared_feature_order() -> None:
    priors = [_game(day=0, points=10), _game(day=7, points=12)]
    features = compute_features(priors, is_home=1, days_rest=7)
    vector = to_vector(features)
    assert len(vector) == len(FEATURE_NAMES)
    assert set(features) == set(FEATURE_NAMES)


def test_features_reflect_context_and_history() -> None:
    priors = [_game(day=0, points=10), _game(day=7, points=20)]
    features = compute_features(priors, is_home=0, days_rest=3)
    assert features["games_played"] == 2
    assert features["last_game_points"] == 20.0
    assert features["is_home"] == 0.0
    assert features["days_rest"] == 3.0
    assert features["pts_avg_season"] == 15.0


def test_days_rest_is_clamped() -> None:
    priors = [_game(day=0, points=10), _game(day=7, points=12)]
    features = compute_features(priors, is_home=1, days_rest=90)
    assert features["days_rest"] == 14.0


def test_training_examples_are_point_in_time() -> None:
    games = [
        _game(day=0, points=10),
        _game(day=7, points=12),
        _game(day=14, points=14),
        _game(day=21, points=16),
    ]
    examples = build_training_examples({"p1": games})

    # First MIN_HISTORY games can't be targets (no prior form).
    assert len(examples) == len(games) - MIN_HISTORY
    assert [e.label for e in examples] == [14.0, 16.0]

    # The label game must never contribute to its own features.
    assert examples[0].features["last_game_points"] == 12.0
    assert examples[1].features["last_game_points"] == 14.0
