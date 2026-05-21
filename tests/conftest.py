from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from courtside.auth.tokens import hash_password
from courtside.db.models import Base, Player, Position, Team, User
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
