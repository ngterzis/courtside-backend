from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from courtside.config import get_settings


class InvalidTokenError(Exception):
    """Raised when an access token is malformed, expired, or carries a bad sub.

    Distinct from jwt.InvalidTokenError, which it wraps — callers depend on
    this module's exception rather than PyJWT's.
    """


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(player_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(player_id),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.jwt_expiry_minutes)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(str(exc)) from exc
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise InvalidTokenError("missing sub")
    try:
        return UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("invalid sub") from exc
