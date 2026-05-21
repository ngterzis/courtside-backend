from datetime import datetime
from enum import StrEnum
from uuid import UUID

from courtside.schemas.base import CamelModel


class ArchetypeName(StrEnum):
    PLAYMAKER = "Playmaker"
    EFFICIENT_SCORER = "Efficient Scorer"
    GLASS_CLEANER = "Glass Cleaner"
    DEFENSIVE_ANCHOR = "Defensive Anchor"
    THREE_AND_D_WING = "3&D Wing"
    RIM_PROTECTOR = "Rim Protector"
    SPARK_PLUG = "Spark Plug"
    FLOOR_GENERAL = "Floor General"
    HUSTLE_PLAYER = "Hustle Player"


class ArchetypeReceiptLine(CamelModel):
    stat: str
    value: str
    percentile: float
    comment: str


class ArchetypeScore(CamelModel):
    name: str
    score: float
    is_primary: bool | None = None
    is_secondary: bool | None = None


class ArchetypeOut(CamelModel):
    primary: ArchetypeName
    secondary: ArchetypeName
    explanation: str
    receipt: list[ArchetypeReceiptLine]
    scores: list[ArchetypeScore] | None = None
    assigned_at: datetime
    season_id: UUID
