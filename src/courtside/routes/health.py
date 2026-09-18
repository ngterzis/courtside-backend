from fastapi import Depends, Response
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from courtside.config import get_settings
from courtside.db.models import Team
from courtside.db.session import get_db
from courtside.routes import CamelRouter
from courtside.schemas.health import HealthOut

router = CamelRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut)
def health(response: Response, db: Session = Depends(get_db)) -> HealthOut:
    """Readiness, not just liveness.

    deploy.yml rolls the Lambdas back when this endpoint stops answering "ok",
    so it has to fail whenever the new image cannot actually serve traffic. A
    bare 200 would only prove the process booted — it would report healthy with
    Aurora unreachable or with a half-applied migration, and certify exactly
    the deploys the rollback exists to catch.
    """
    settings = get_settings()

    try:
        db.execute(text("SELECT 1"))
        # A mapped SELECT fails when the ORM and the schema disagree about
        # columns; SELECT 1 alone cannot see that.
        db.execute(select(Team.id).limit(1))
    except SQLAlchemyError as exc:
        response.status_code = 503
        return HealthOut(status="unhealthy", env=settings.env, error=type(exc).__name__)

    revision: str | None = None
    try:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        # Absent under pytest, which builds the schema with create_all rather
        # than by migrating. Reported as null instead of failing the check.
        db.rollback()

    return HealthOut(status="ok", env=settings.env, revision=revision)
