from datetime import date, datetime
from uuid import UUID

from courtside.db.models import HomeAway, Result
from courtside.schemas.base import CamelModel


class CoachNoteOut(CamelModel):
    id: UUID
    game_id: UUID
    author_name: str
    text: str
    created_at: datetime


class GameStatsOut(CamelModel):
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    fg_made: int
    fg_attempted: int
    three_made: int
    three_attempted: int
    ft_made: int
    ft_attempted: int
    fg_pct: float
    three_pct: float
    ft_pct: float
    ts_pct: float


class GameOut(CamelModel):
    id: UUID
    season_id: UUID
    date: date
    opponent: str
    home_away: HomeAway
    result: Result
    team_score: int
    opponent_score: int
    stats: GameStatsOut
    personal_bests: list[str]
    coach_note: CoachNoteOut | None = None


class PaginatedGames(CamelModel):
    games: list[GameOut]
    total: int
