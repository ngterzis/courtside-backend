from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from courtside.db.models import GamePerformance, HomeAway, Player, Result, Season
from courtside.services.games import get_or_create_game

DEFAULT_STATS: dict[str, int] = {
    "points": 20,
    "rebounds": 5,
    "assists": 4,
    "steals": 1,
    "blocks": 0,
    "turnovers": 2,
    "fouls": 2,
    "fg2_made": 8,
    "fg2_attempted": 16,
    "three_made": 2,
    "three_attempted": 6,
    "ft_made": 4,
    "ft_attempted": 5,
}


def add_performance(
    db: Session,
    player: Player,
    season: Season,
    day: date,
    *,
    opponent: str = "Rivals",
    home_away: HomeAway = HomeAway.HOME,
    result: Result = Result.WIN,
    **stats: Any,
) -> GamePerformance:
    """Add the player's stat line for the season's game on `day`, creating the game.

    Teammates given the same day and opponent share one games row.
    """
    game = get_or_create_game(
        db,
        season_id=season.id,
        date=day,
        opponent=opponent,
        home_away=home_away,
        result=result,
        team_score=80 if result == Result.WIN else 70,
        opponent_score=70 if result == Result.WIN else 80,
    )
    perf = GamePerformance(
        game_id=game.id, player_id=player.id, **{**DEFAULT_STATS, **stats}
    )
    db.add(perf)
    db.flush()
    return perf
