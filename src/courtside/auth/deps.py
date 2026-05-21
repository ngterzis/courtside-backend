from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from courtside.auth.tokens import InvalidToken, decode_access_token
from courtside.db.models import Player
from courtside.db.session import get_db
from courtside.errors import APIError

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> APIError:
    return APIError(401, "unauthorized", "Missing or invalid token")


def get_current_player(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Player:
    if creds is None:
        raise _unauthorized()
    try:
        player_id = decode_access_token(creds.credentials)
    except InvalidToken as exc:
        raise _unauthorized() from exc
    player = db.get(Player, player_id)
    if player is None:
        raise _unauthorized()
    return player
