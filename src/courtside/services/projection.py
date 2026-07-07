"""Assemble a next-game points projection for a player and persist it.

Features are computed from the player's games in the active season via the shared
`courtside.ml.features` code, then handed to `courtside.ml.client` which either calls
the SageMaker endpoint or returns the trailing-average baseline. Every served
projection is written to `predictions` so it can later be joined to the actual next
game for offline monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Game, Player, Prediction, Season
from courtside.ml.client import PointsPrediction, baseline_prediction, predict_points
from courtside.ml.features import MIN_HISTORY, latest_features


@dataclass
class ProjectionResult:
    player_id: UUID
    predicted_points: float
    baseline_points: float
    games_considered: int
    model_version: str
    source: str


def build_projection(
    db: Session,
    player: Player,
    *,
    is_home: int = 1,
    days_rest: int | None = None,
) -> ProjectionResult:
    season = db.scalar(
        select(Season).where(
            Season.team_id == player.team_id, Season.end_date.is_(None)
        )
    )
    games: list[Game] = []
    if season is not None:
        games = list(
            db.scalars(
                select(Game)
                .where(Game.player_id == player.id, Game.season_id == season.id)
                .order_by(Game.date)
            ).all()
        )

    if not games:
        return ProjectionResult(
            player_id=player.id,
            predicted_points=0.0,
            baseline_points=0.0,
            games_considered=0,
            model_version="baseline-trailing-avg",
            source="baseline",
        )

    if days_rest is None:
        days_rest = (date.today() - games[-1].date).days

    if len(games) >= MIN_HISTORY:
        features = latest_features(games, is_home=is_home, days_rest=days_rest)
        pred: PointsPrediction = predict_points(features, games)
    else:
        pred = baseline_prediction(games)

    db.add(
        Prediction(
            team_id=player.team_id,
            player_id=player.id,
            as_of_date=games[-1].date,
            predicted_points=pred.predicted_points,
            baseline_points=pred.baseline_points,
            model_version=pred.model_version,
            source=pred.source,
        )
    )
    db.commit()

    return ProjectionResult(
        player_id=player.id,
        predicted_points=pred.predicted_points,
        baseline_points=pred.baseline_points,
        games_considered=len(games),
        model_version=pred.model_version,
        source=pred.source,
    )
