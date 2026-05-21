from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import Game, Player, Season
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.stats import SeasonAverages, TeamRank
from courtside.services.stats import season_averages, team_ranks

router = CamelRouter(tags=["stats"])

DEFAULT_RANK_STATS = ("assists", "rebounds", "steals", "three_pct")


def _current_season_id(db: Session, team_id: UUID) -> UUID:
    season_id = db.scalar(
        select(Season.id).where(
            Season.team_id == team_id, Season.end_date.is_(None)
        )
    )
    if season_id is None:
        raise APIError(404, "no_active_season", "No active season for this team")
    return season_id


@router.get("/api/me/season-averages", response_model=SeasonAverages)
def get_season_averages(
    season_id: UUID | None = Query(None, alias="seasonId"),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> SeasonAverages:
    if season_id is None:
        season_id = _current_season_id(db, player.team_id)
    games = list(
        db.scalars(
            select(Game).where(
                Game.player_id == player.id, Game.season_id == season_id
            )
        ).all()
    )
    return SeasonAverages.model_validate(season_averages(games, season_id))


@router.get("/api/me/team-ranks", response_model=list[TeamRank])
def get_team_ranks(
    season_id: UUID | None = Query(None, alias="seasonId"),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> list[TeamRank]:
    if season_id is None:
        season_id = _current_season_id(db, player.team_id)
    rows = team_ranks(
        db,
        team_id=player.team_id,
        season_id=season_id,
        player_id=player.id,
        stats=DEFAULT_RANK_STATS,
    )
    return [TeamRank.model_validate(r) for r in rows]
