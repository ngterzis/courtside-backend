from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from courtside.db.models import Base
from courtside.db.session import build_engine


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    e = build_engine()
    Base.metadata.drop_all(e)
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
