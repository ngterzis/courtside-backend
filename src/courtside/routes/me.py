from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import Player
from courtside.db.session import get_db
from courtside.routes import CamelRouter
from courtside.schemas.auth import OnboardRequest
from courtside.schemas.player import PlayerOut

router = CamelRouter(tags=["me"])


@router.get("/api/me", response_model=PlayerOut)
def get_me(player: Player = Depends(get_current_player)) -> PlayerOut:
    return PlayerOut.model_validate(player)


@router.post("/api/me/onboard", response_model=PlayerOut)
def onboard(
    payload: OnboardRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> PlayerOut:
    player.jersey_number = payload.jersey_number
    player.position = payload.position
    player.onboarded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(player)
    return PlayerOut.model_validate(player)
