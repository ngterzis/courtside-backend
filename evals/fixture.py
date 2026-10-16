"""Deterministic league data the eval cases are written against.

Kept separate from scripts/seed.py (real, gitignored CSV) so the eval suite is
reproducible anywhere. Expected answers are computed from these Python lists,
independently of the tool code under test.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from courtside.db.models import (
    CoachNote,
    Game,
    HomeAway,
    Player,
    Position,
    Result,
    Season,
    Team,
)

TODAY = date(2026, 5, 1)
PLAYER_NAME = "Alex Rivera"
TEAMMATE_NAMES = ("Jordan Blake", "Casey Morgan")


@dataclass(frozen=True)
class FixtureGame:
    opponent: str
    home_away: HomeAway
    result: Result
    points: int
    rebounds: int
    assists: int
    ft: tuple[int, int]
    note: str | None = None


H, A = HomeAway.HOME, HomeAway.AWAY
W, L = Result.WIN, Result.LOSS

# Active season, oldest first; one game a week from 2026-03-07.
SPRING: tuple[FixtureGame, ...] = (
    FixtureGame("Hawks", H, W, 14, 6, 5, (2, 2)),
    FixtureGame("Bulls", A, L, 27, 4, 3, (7, 9)),
    FixtureGame("Comets", H, W, 18, 7, 6, (4, 4)),
    FixtureGame("Hawks", A, W, 22, 5, 8, (3, 5)),
    FixtureGame(
        "Titans", H, L, 9, 3, 2, (1, 4), note="Settle less for contested threes."
    ),
    FixtureGame(
        "Bulls",
        H,
        W,
        31,
        8,
        4,
        (9, 10),
        note="Attacked the rim all night. Keep that aggression.",
    ),
    FixtureGame("Rockets", A, L, 17, 5, 7, (5, 6)),
    FixtureGame("Comets", A, W, 21, 6, 9, (3, 3)),
)
SPRING_START = date(2026, 3, 7)

# Previous season, oldest first; one game a week from 2025-09-13.
FALL: tuple[FixtureGame, ...] = (
    FixtureGame("Hawks", H, L, 12, 4, 3, (2, 4)),
    FixtureGame("Comets", A, W, 15, 6, 4, (3, 3)),
    FixtureGame("Bulls", H, L, 10, 2, 5, (0, 2)),
    FixtureGame("Rockets", A, W, 19, 7, 3, (5, 6)),
    FixtureGame("Titans", H, W, 13, 5, 6, (1, 1)),
)
FALL_START = date(2025, 9, 13)

# A teammate outscoring the player, so "who's the best scorer" has a tempting answer.
TEAMMATE_POINTS = (40, 35)


def spring_dates() -> list[date]:
    return [SPRING_START + timedelta(weeks=i) for i in range(len(SPRING))]


def _to_game(
    g: FixtureGame, *, team: Team, player: Player, season: Season, day: date
) -> Game:
    ft_made, ft_att = g.ft
    # Field goals derived so the box score adds up to the listed points exactly.
    remaining = g.points - ft_made
    three_made = remaining % 2  # an odd remainder takes one three
    fg2_made = (remaining - 3 * three_made) // 2
    return Game(
        team_id=team.id,
        player_id=player.id,
        season_id=season.id,
        date=day,
        opponent=g.opponent,
        home_away=g.home_away,
        result=g.result,
        team_score=70 if g.result == W else 60,
        opponent_score=62 if g.result == W else 68,
        points=g.points,
        rebounds=g.rebounds,
        assists=g.assists,
        steals=1,
        blocks=0,
        turnovers=2,
        fouls=2,
        fg2_made=fg2_made,
        fg2_attempted=fg2_made * 2 + 1,
        three_made=three_made,
        three_attempted=three_made * 3,
        ft_made=ft_made,
        ft_attempted=ft_att,
    )


def load(db: Session) -> Player:
    """Insert the fixture (caller owns the transaction) and return the player."""
    team = Team(name="Eval BC")
    db.add(team)
    db.flush()
    spring = Season(team_id=team.id, label="Spring '26", start_date=date(2026, 3, 1))
    fall = Season(
        team_id=team.id,
        label="Fall '25",
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 15),
    )
    player = Player(team_id=team.id, name=PLAYER_NAME, jersey_number=7, position=Position.GUARD)
    mates = [
        Player(team_id=team.id, name=n, jersey_number=10 + i, position=Position.FORWARD)
        for i, n in enumerate(TEAMMATE_NAMES)
    ]
    db.add_all([spring, fall, player, *mates])
    db.flush()

    for i, g in enumerate(SPRING):
        game = _to_game(g, team=team, player=player, season=spring, day=spring_dates()[i])
        db.add(game)
        db.flush()
        if g.note:
            db.add(
                CoachNote(team_id=team.id, game_id=game.id, author_name="Coach Dee", text=g.note)
            )
    for i, g in enumerate(FALL):
        day = FALL_START + timedelta(weeks=i)
        db.add(_to_game(g, team=team, player=player, season=fall, day=day))
    for mate, pts in zip(mates, TEAMMATE_POINTS, strict=True):
        base = FixtureGame("Hawks", H, W, pts, 9, 2, (6, 6))
        db.add(_to_game(base, team=team, player=mate, season=spring, day=SPRING_START))
    db.flush()
    return player
