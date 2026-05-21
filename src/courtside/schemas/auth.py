from pydantic import EmailStr

from courtside.db.models import Position
from courtside.schemas.base import CamelModel
from courtside.schemas.player import PlayerOut


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class LoginResponse(CamelModel):
    token: str
    player: PlayerOut


class OnboardRequest(CamelModel):
    jersey_number: int
    position: Position
