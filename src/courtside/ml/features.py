"""Point-in-time feature computation for the next-game points model.

Every feature row is built from a player's games *strictly before* the game being
predicted, so a training set assembled here never leaks the target. The same
function feeds request-time serving (`services/projection.py`) and offline training
(`ml/training/train.py`), which is what keeps train and serve in lockstep.
"""

from __future__ import annotations

from dataclasses import dataclass

from courtside.db.models import Game, HomeAway
from courtside.services.stats import season_averages

# Minimum prior games (within the same season) before we'll emit a feature row.
# Below this there isn't enough form signal and the averages are too noisy.
MIN_HISTORY = 2

# Fixed order = the model's input vector. Never reorder in place; append only, and
# retrain when you do. Serving and training both read this list.
FEATURE_NAMES: tuple[str, ...] = (
    "games_played",
    "pts_avg_3",
    "reb_avg_3",
    "ast_avg_3",
    "tov_avg_3",
    "fga_avg_3",
    "ts_pct_3",
    "fg_pct_3",
    "three_pct_3",
    "pts_avg_5",
    "reb_avg_5",
    "ast_avg_5",
    "ts_pct_5",
    "pts_avg_season",
    "reb_avg_season",
    "ast_avg_season",
    "ts_pct_season",
    "last_game_points",
    "days_rest",
    "is_home",
    "opp_margin_avg",
)


@dataclass
class TrainingExample:
    player_id: str
    event_date: str  # ISO date of the target game — the feature record's event time
    features: dict[str, float]
    label: float  # actual points scored in the target game


def _clamp_days_rest(days: int) -> float:
    # A long layoff (new season, injury gap) carries little signal and would
    # otherwise dominate the feature; cap it at two weeks.
    return float(max(0, min(days, 14)))


def compute_features(
    prior_games: list[Game],
    *,
    is_home: int,
    days_rest: int,
) -> dict[str, float]:
    """Feature row from same-season games that precede the target.

    `prior_games` must be the player's games in the target's season, ordered oldest
    first, all dated before the target game. `is_home`/`days_rest` describe the
    upcoming game's context.
    """
    if not prior_games:
        raise ValueError("compute_features requires at least one prior game")

    season_id = prior_games[0].season_id
    last3 = season_averages(prior_games[-3:], season_id)
    last5 = season_averages(prior_games[-5:], season_id)
    season = season_averages(prior_games, season_id)
    margins = [g.team_score - g.opponent_score for g in prior_games]

    return {
        "games_played": float(len(prior_games)),
        "pts_avg_3": last3["points"],
        "reb_avg_3": last3["rebounds"],
        "ast_avg_3": last3["assists"],
        "tov_avg_3": last3["turnovers"],
        "fga_avg_3": last3["fg_attempted"],
        "ts_pct_3": last3["ts_pct"],
        "fg_pct_3": last3["fg_pct"],
        "three_pct_3": last3["three_pct"],
        "pts_avg_5": last5["points"],
        "reb_avg_5": last5["rebounds"],
        "ast_avg_5": last5["assists"],
        "ts_pct_5": last5["ts_pct"],
        "pts_avg_season": season["points"],
        "reb_avg_season": season["rebounds"],
        "ast_avg_season": season["assists"],
        "ts_pct_season": season["ts_pct"],
        "last_game_points": float(prior_games[-1].points),
        "days_rest": _clamp_days_rest(days_rest),
        "is_home": float(is_home),
        "opp_margin_avg": sum(margins) / len(margins),
    }


def to_vector(features: dict[str, float]) -> list[float]:
    """Ordered feature vector for model input (CSV row / DataFrame column order)."""
    return [features[name] for name in FEATURE_NAMES]


def latest_features(
    season_games: list[Game],
    *,
    is_home: int,
    days_rest: int,
) -> dict[str, float]:
    """Feature row for a player's *next* (unplayed) game, from all season games so far."""
    ordered = sorted(season_games, key=lambda g: g.date)
    return compute_features(ordered, is_home=is_home, days_rest=days_rest)


def build_training_examples(games_by_player: dict[str, list[Game]]) -> list[TrainingExample]:
    """Sliding-window training rows: for each game with >= MIN_HISTORY same-season
    predecessors, features come from the predecessors and the label is that game's points.
    """
    examples: list[TrainingExample] = []
    for player_id, games in games_by_player.items():
        ordered = sorted(games, key=lambda g: (g.season_id.hex, g.date))
        by_season: dict[str, list[Game]] = {}
        for g in ordered:
            by_season.setdefault(g.season_id.hex, []).append(g)

        for season_games in by_season.values():
            for i, target in enumerate(season_games):
                prior = season_games[:i]
                if len(prior) < MIN_HISTORY:
                    continue
                days_rest = (target.date - prior[-1].date).days
                is_home = 1 if target.home_away == HomeAway.HOME else 0
                examples.append(
                    TrainingExample(
                        player_id=player_id,
                        event_date=target.date.isoformat(),
                        features=compute_features(
                            prior, is_home=is_home, days_rest=days_rest
                        ),
                        label=float(target.points),
                    )
                )
    return examples
