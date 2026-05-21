"""Wipe local data and load deterministic seed data.

Usage:
    uv run python scripts/seed.py
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from courtside.auth.tokens import hash_password
from courtside.db.models import (
    Archetype,
    CoachNote,
    Game,
    HomeAway,
    Notification,
    Player,
    Position,
    Result,
    Season,
    Team,
    User,
)
from courtside.db.session import get_session_factory

SEED_EMAIL = "player@courtside.dev"
SEED_PASSWORD = "password123"


def _wipe(db: object) -> None:
    for model in (Notification, Archetype, CoachNote, Game, Season, User, Player, Team):
        db.execute(delete(model))  # type: ignore[attr-defined]


def _make_game(
    rng: random.Random,
    team_id,
    player_id,
    season_id,
    game_date: date,
    opponent: str,
    home_away: HomeAway,
) -> Game:
    fg_attempted = rng.randint(8, 18)
    fg_made = rng.randint(3, fg_attempted)
    three_attempted = rng.randint(2, 8)
    three_made = rng.randint(0, three_attempted)
    ft_attempted = rng.randint(2, 8)
    ft_made = rng.randint(0, ft_attempted)
    points = fg_made * 2 + three_made + ft_made

    team_score = rng.randint(60, 92)
    opp_score = rng.randint(55, 92)
    while team_score == opp_score:
        opp_score = rng.randint(55, 92)
    result = Result.WIN if team_score > opp_score else Result.LOSS

    return Game(
        team_id=team_id,
        player_id=player_id,
        season_id=season_id,
        date=game_date,
        opponent=opponent,
        home_away=home_away,
        result=result,
        team_score=team_score,
        opponent_score=opp_score,
        points=points,
        rebounds=rng.randint(2, 9),
        assists=rng.randint(2, 10),
        steals=rng.randint(0, 4),
        blocks=rng.randint(0, 3),
        turnovers=rng.randint(0, 5),
        fouls=rng.randint(0, 4),
        fg_made=fg_made,
        fg_attempted=fg_attempted,
        three_made=three_made,
        three_attempted=three_attempted,
        ft_made=ft_made,
        ft_attempted=ft_attempted,
    )


def main() -> None:
    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        _wipe(db)
        db.commit()

        team = Team(name="The Falcons")
        db.add(team)
        db.flush()

        main_player = Player(
            team_id=team.id,
            name="Alex Reyes",
            jersey_number=23,
            position=Position.GUARD,
            onboarded_at=datetime.now(timezone.utc),
        )
        teammates = [
            Player(team_id=team.id, name="Jamie Park", jersey_number=4, position=Position.GUARD),
            Player(team_id=team.id, name="Sam Liu", jersey_number=11, position=Position.FORWARD),
            Player(team_id=team.id, name="Chris Nguyen", jersey_number=14, position=Position.FORWARD),
            Player(team_id=team.id, name="Pat Brown", jersey_number=42, position=Position.CENTER),
        ]
        db.add_all([main_player, *teammates])
        db.flush()

        db.add(
            User(
                email=SEED_EMAIL,
                password_hash=hash_password(SEED_PASSWORD),
                player_id=main_player.id,
            )
        )

        prev_season = Season(
            team_id=team.id,
            label="Fall '25",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
        )
        current_season = Season(
            team_id=team.id,
            label="Spring '26",
            start_date=date(2026, 3, 1),
            end_date=None,
        )
        db.add_all([prev_season, current_season])
        db.flush()

        rng = random.Random(42)
        opponents = ["Riverside", "Eagles", "Hawks", "Bulldogs", "Knights", "Wolves", "Tigers"]
        first_game = date(2026, 3, 7)
        for i in range(8):
            db.add(
                _make_game(
                    rng,
                    team.id,
                    main_player.id,
                    current_season.id,
                    first_game + timedelta(weeks=i),
                    opponents[i % len(opponents)],
                    HomeAway.HOME if i % 2 == 0 else HomeAway.AWAY,
                )
            )

        for tm in teammates:
            for i in range(6):
                db.add(
                    _make_game(
                        rng,
                        team.id,
                        tm.id,
                        current_season.id,
                        first_game + timedelta(weeks=i),
                        opponents[i % len(opponents)],
                        HomeAway.HOME if i % 2 == 0 else HomeAway.AWAY,
                    )
                )
        db.flush()

        last_game = db.scalar(
            select(Game)
            .where(Game.player_id == main_player.id)
            .order_by(Game.date.desc())
            .limit(1)
        )
        if last_game is not None:
            db.add(
                CoachNote(
                    team_id=team.id,
                    game_id=last_game.id,
                    author_name="Coach Wilson",
                    text="Great court vision tonight — keep finding the open guy.",
                )
            )

        team_name = team.name
        main_name = main_player.name
        main_number = main_player.jersey_number
        current_label = current_season.label
        games_main = 8
        games_teammates = len(teammates) * 6

        db.commit()

    print("Seed complete.")
    print(f"  team:        {team_name}")
    print(f"  main player: {main_name} (#{main_number})")
    print(f"  teammates:   {len(teammates)}")
    print(f"  seasons:     2 (current: {current_label})")
    print(f"  games:       {games_main} for main, {games_teammates} across teammates")
    print()
    print("Login:")
    print(f"  email:    {SEED_EMAIL}")
    print(f"  password: {SEED_PASSWORD}")


if __name__ == "__main__":
    main()
