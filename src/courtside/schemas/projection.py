from uuid import UUID

from courtside.schemas.base import CamelModel


class Projection(CamelModel):
    player_id: UUID
    predicted_points: float
    baseline_points: float
    games_considered: int
    model_version: str
    source: str
