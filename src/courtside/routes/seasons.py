from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import Player, Season
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.season import SeasonOut

router = CamelRouter(tags=["seasons"])


@router.get("/api/seasons", response_model=list[SeasonOut])
def list_seasons(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> list[SeasonOut]:
    seasons = db.scalars(
        select(Season)
        .where(Season.team_id == player.team_id)
        .order_by(Season.start_date.desc())
    ).all()
    return [SeasonOut.model_validate(s) for s in seasons]


@router.get("/api/seasons/current", response_model=SeasonOut)
def current_season(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> SeasonOut:
    season = db.scalar(
        select(Season).where(
            Season.team_id == player.team_id, Season.end_date.is_(None)
        )
    )
    if season is None:
        raise APIError(404, "no_active_season", "No active season for this team")
    return SeasonOut.model_validate(season)
