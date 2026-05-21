from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.auth.tokens import create_access_token, verify_password
from courtside.db.models import Player, User
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.auth import LoginRequest, LoginResponse
from courtside.schemas.player import PlayerOut

router = CamelRouter(tags=["auth"])


def _invalid_credentials() -> APIError:
    return APIError(401, "invalid_credentials", "Email or password incorrect")


@router.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise _invalid_credentials()
    if user.player_id is None:
        raise _invalid_credentials()
    player = db.get(Player, user.player_id)
    if player is None:
        raise _invalid_credentials()
    return LoginResponse(
        token=create_access_token(player.id),
        player=PlayerOut.model_validate(player),
    )


@router.post("/api/auth/logout")
def logout() -> dict[str, Any]:
    return {}
