from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from courtside.config import Settings, get_settings


def build_url(settings: Settings) -> str:
    if settings.use_data_api:
        return f"postgresql+auroradataapi://:@/{settings.db_name}"
    if settings.database_url:
        return settings.database_url
    return (
        f"postgresql+psycopg://"
        f"{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = build_url(settings)
    if settings.use_data_api:
        import boto3

        # aurora_data_api.connect() takes `secret_arn` (not `aurora_secret_arn`)
        # and has no region argument — the region is carried by the boto3 client.
        return create_engine(
            url,
            connect_args={
                "aurora_cluster_arn": settings.db_cluster_arn,
                "secret_arn": settings.db_secret_arn,
                "rds_data_client": boto3.client("rds-data", region_name=settings.aws_region),
            },
            # The Data API returns UUIDs as strings, so SQLAlchemy's batched
            # insertmanyvalues can't match its UUID sentinels. Fall back to plain
            # inserts (our client-side uuid4 PKs make RETURNING unnecessary).
            use_insertmanyvalues=False,
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
