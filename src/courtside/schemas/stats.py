from uuid import UUID

from courtside.schemas.base import CamelModel


class SeasonAverages(CamelModel):
    season_id: UUID
    games_played: int
    points: float
    rebounds: float
    assists: float
    steals: float
    blocks: float
    turnovers: float
    fouls: float
    fg_made: float
    fg_attempted: float
    three_made: float
    three_attempted: float
    ft_made: float
    ft_attempted: float
    fg_pct: float
    three_pct: float
    ft_pct: float
    ts_pct: float


class TeamRank(CamelModel):
    stat: str
    percentile: float
    label: str
