"""Naive trailing-average baseline.

This is both the yardstick the trained model must beat (logged alongside every
training run) and the graceful fallback the serving path returns when no SageMaker
endpoint is configured. Keeping it here means serving never depends on the offline
training package or any ML library.
"""

from __future__ import annotations

from courtside.db.models import Game

DEFAULT_WINDOW = 3


def trailing_average_points(prior_games: list[Game], window: int = DEFAULT_WINDOW) -> float:
    """Mean points over the most recent `window` games (fewer if that's all there is)."""
    if not prior_games:
        return 0.0
    ordered = sorted(prior_games, key=lambda g: g.date)
    recent = ordered[-window:]
    return sum(g.points for g in recent) / len(recent)
