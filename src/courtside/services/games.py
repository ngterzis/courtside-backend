from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from courtside.db.models import Game, GamePerformance, HomeAway, Result


def player_performances(
    db: Session, player_id: UUID, season_id: UUID | None = None
) -> list[GamePerformance]:
    """The player's stat lines, newest game first, each with its game loaded.

    season_id=None covers every season.
    """
    stmt = (
        select(GamePerformance)
        .join(GamePerformance.game)
        .options(contains_eager(GamePerformance.game))
        .where(GamePerformance.player_id == player_id)
        .order_by(Game.date.desc())
    )
    if season_id is not None:
        stmt = stmt.where(Game.season_id == season_id)
    return list(db.scalars(stmt).all())


def get_or_create_game(
    db: Session,
    *,
    season_id: UUID,
    date: date,
    opponent: str,
    home_away: HomeAway,
    result: Result,
    team_score: int,
    opponent_score: int,
) -> Game:
    """The season's game on `date` against `opponent`, created if it isn't there yet.

    Loaders add one performance per player, so every teammate after the first
    finds the game the first one created. Raises if their game facts disagree.
    """
    facts = {
        "home_away": home_away,
        "result": result,
        "team_score": team_score,
        "opponent_score": opponent_score,
    }
    game = db.scalar(
        select(Game).where(
            Game.season_id == season_id, Game.date == date, Game.opponent == opponent
        )
    )
    if game is None:
        game = Game(season_id=season_id, date=date, opponent=opponent, **facts)
        db.add(game)
        db.flush()
        return game
    stored = {k: getattr(game, k) for k in facts}
    if stored != facts:
        raise ValueError(f"{date} vs {opponent} already recorded as {stored}, not {facts}")
    return game
