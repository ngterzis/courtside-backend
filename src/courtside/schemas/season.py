from datetime import date
from uuid import UUID

from courtside.schemas.base import CamelModel


class SeasonOut(CamelModel):
    id: UUID
    label: str
    start_date: date
    end_date: date | None = None
