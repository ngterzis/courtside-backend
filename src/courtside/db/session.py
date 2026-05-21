from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from courtside.config import Settings, get_settings


def build_url(settings: Settings) -> str:
    if settings.db_driver == "aurora_data_api":
        return f"postgresql+auroradataapi://:@/{settings.aurora_database_name}"
    return (
        f"postgresql+psycopg://"
        f"{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = build_url(settings)
    if settings.db_driver == "aurora_data_api":
        return create_engine(
            url,
            connect_args={
                "aurora_cluster_arn": settings.aurora_cluster_arn,
                "aurora_secret_arn": settings.aurora_secret_arn,
                "region_name": settings.aws_region,
            },
        )
    return create_engine(url, pool_pre_ping=True)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = build_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
