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


# Feedback tokens let the client rate one chat answer. They bind a trace id to a
# player and are deliberately unusable as access tokens: no `sub` claim, and an
# `aud` that decode_access_token (which passes no audience) rejects.
_FEEDBACK_AUDIENCE = "chat_feedback"
_FEEDBACK_EXPIRY = timedelta(days=7)


def create_feedback_token(trace_id: str, player_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "aud": _FEEDBACK_AUDIENCE,
        "tid": trace_id,
        "pid": str(player_id),
        "iat": int(now.timestamp()),
        "exp": int((now + _FEEDBACK_EXPIRY).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_feedback_token(token: str) -> tuple[str, UUID]:
    """Return (trace_id, player_id) from a feedback token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=["HS256"], audience=_FEEDBACK_AUDIENCE
        )
        trace_id, player_id = payload["tid"], UUID(payload["pid"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError(str(exc)) from exc
    if not isinstance(trace_id, str):
        raise InvalidTokenError("invalid tid")
    return trace_id, player_id
