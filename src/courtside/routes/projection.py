from fastapi import Depends, Query
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import Player
from courtside.db.session import get_db
from courtside.routes import CamelRouter
from courtside.schemas.projection import Projection
from courtside.services.projection import build_projection

router = CamelRouter(tags=["projection"])


@router.get("/api/me/projection", response_model=Projection)
def get_projection(
    is_home: bool = Query(True, alias="isHome"),
    days_rest: int | None = Query(None, alias="daysRest"),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> Projection:
    result = build_projection(
        db, player, is_home=int(is_home), days_rest=days_rest
    )
    return Projection.model_validate(result)
