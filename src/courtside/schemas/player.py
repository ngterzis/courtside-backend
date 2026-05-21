from datetime import datetime
from uuid import UUID

from courtside.db.models import Position
from courtside.schemas.base import CamelModel


class PlayerOut(CamelModel):
    id: UUID
    name: str
    jersey_number: int
    position: Position
    team_id: UUID
    onboarded_at: datetime | None = None
