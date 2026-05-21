from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from courtside.auth.tokens import hash_password
from courtside.db.models import (
    Base,
    Game,
    HomeAway,
    Player,
    Position,
    Result,
    Season,
    Team,
    User,
)
from courtside.db.session import build_engine, get_db
from courtside.main import app


def _reset_schema(e: Engine) -> None:
    Base.metadata.drop_all(e)
    with e.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    e = build_engine()
    _reset_schema(e)
    Base.metadata.create_all(e)
    yield e
    _reset_schema(e)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def team(db: Session) -> Team:
    t = Team(name="Test Team")
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def player(db: Session, team: Team) -> Player:
    p = Player(
        team_id=team.id,
        name="Test Player",
        jersey_number=10,
        position=Position.GUARD,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def user(db: Session, player: Player) -> User:
    u = User(
        email="player@example.com",
        password_hash=hash_password("secret"),
        player_id=player.id,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def current_season(db: Session, team: Team) -> Season:
    s = Season(
        team_id=team.id,
        label="Spring '26",
        start_date=date(2026, 3, 1),
        end_date=None,
    )
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def previous_season(db: Session, team: Team) -> Season:
    s = Season(
        team_id=team.id,
        label="Fall '25",
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 15),
    )
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def teammates(db: Session, team: Team) -> list[Player]:
    mates = [
        Player(team_id=team.id, name="Jamie Park", jersey_number=4, position=Position.GUARD),
        Player(team_id=team.id, name="Sam Liu", jersey_number=11, position=Position.FORWARD),
        Player(team_id=team.id, name="Pat Brown", jersey_number=42, position=Position.CENTER),
    ]
    db.add_all(mates)
    db.flush()
    return mates


def _build_game(
    *,
    team_id,
    player_id,
    season_id,
    game_date: date,
    points: int = 20,
    rebounds: int = 5,
    assists: int = 4,
    steals: int = 1,
    blocks: int = 0,
    turnovers: int = 2,
    fouls: int = 2,
    fg_made: int = 8,
    fg_attempted: int = 16,
    three_made: int = 2,
    three_attempted: int = 6,
    ft_made: int = 4,
    ft_attempted: int = 5,
    result: Result = Result.WIN,
) -> Game:
    return Game(
        team_id=team_id,
        player_id=player_id,
        season_id=season_id,
        date=game_date,
        opponent="Rivals",
        home_away=HomeAway.HOME,
        result=result,
        team_score=80 if result == Result.WIN else 70,
        opponent_score=70 if result == Result.WIN else 80,
        points=points,
        rebounds=rebounds,
        assists=assists,
        steals=steals,
        blocks=blocks,
        turnovers=turnovers,
        fouls=fouls,
        fg_made=fg_made,
        fg_attempted=fg_attempted,
        three_made=three_made,
        three_attempted=three_attempted,
        ft_made=ft_made,
        ft_attempted=ft_attempted,
    )


@pytest.fixture
def main_games(
    db: Session, team: Team, player: Player, current_season: Season
) -> list[Game]:
    base = date(2026, 3, 7)
    games = [
        _build_game(
            team_id=team.id,
            player_id=player.id,
            season_id=current_season.id,
            game_date=base + timedelta(weeks=i),
            points=18 + 2 * i,
            assists=3 + i,
        )
        for i in range(3)
    ]
    db.add_all(games)
    db.flush()
    return games


@pytest.fixture
def teammate_games(
    db: Session,
    team: Team,
    teammates: list[Player],
    current_season: Season,
) -> list[Game]:
    base = date(2026, 3, 7)
    games: list[Game] = []
    for idx, p in enumerate(teammates):
        for i in range(3):
            games.append(
                _build_game(
                    team_id=team.id,
                    player_id=p.id,
                    season_id=current_season.id,
                    game_date=base + timedelta(weeks=i),
                    points=10 + idx,
                    rebounds=6 + idx,
                    assists=2,
                    steals=1,
                )
            )
    db.add_all(games)
    db.flush()
    return games
