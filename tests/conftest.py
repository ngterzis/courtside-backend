from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from courtside.auth.tokens import hash_password
from courtside.config import get_settings
from courtside.db.models import (
    Base,
    GamePerformance,
    Player,
    Position,
    Season,
    Team,
    User,
)
from courtside.db.session import build_engine, get_db
from courtside.main import app
from tests.factories import add_performance


def _guard_against_remote_db() -> None:
    """Refuse to run against Aurora via the Data API.

    The `engine` fixture below drops every table before recreating the schema.
    A local .env with USE_DATA_API=true (as used for prod-style development)
    makes build_url() return the Data API URL *before* it ever looks at
    DATABASE_URL, so a bare `pytest` would target the real cluster.
    """
    settings = get_settings()
    if settings.use_data_api:
        raise RuntimeError(
            "Refusing to run tests against the RDS Data API "
            f"(cluster {settings.db_cluster_arn}) — the engine fixture drops every "
            "table. Set USE_DATA_API=false to point at local Postgres."
        )


def _reset_schema(e: Engine) -> None:
    Base.metadata.drop_all(e)
    with e.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never trace from tests, even when .env holds real Langfuse keys.

    Tests that check tracing patch in a fake client on top of this.
    """
    monkeypatch.setattr("courtside.observability.get_langfuse", lambda: None)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _guard_against_remote_db()
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


@pytest.fixture
def main_games(
    db: Session, player: Player, current_season: Season
) -> list[GamePerformance]:
    base = date(2026, 3, 7)
    return [
        add_performance(
            db,
            player,
            current_season,
            base + timedelta(weeks=i),
            points=18 + 2 * i,
            assists=3 + i,
        )
        for i in range(3)
    ]


@pytest.fixture
def teammate_games(
    db: Session,
    teammates: list[Player],
    current_season: Season,
) -> list[GamePerformance]:
    """The teammates' lines in the same three games as main_games."""
    base = date(2026, 3, 7)
    return [
        add_performance(
            db,
            p,
            current_season,
            base + timedelta(weeks=i),
            points=10 + idx,
            rebounds=6 + idx,
            assists=2,
            steals=1,
        )
        for idx, p in enumerate(teammates)
        for i in range(3)
    ]
