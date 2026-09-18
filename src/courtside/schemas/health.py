from typing import Literal

from courtside.schemas.base import CamelModel


class HealthOut(CamelModel):
    status: Literal["ok", "unhealthy"]
    env: str
    revision: str | None = None
    error: str | None = None
