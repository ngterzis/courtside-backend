from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: Literal["local", "dev", "prod"] = "local"

    jwt_secret: str = "dev-only-jwt-secret-replace-in-prod-32-plus-bytes"
    jwt_expiry_minutes: int = 60 * 24 * 7

    # Production (Lambda) talks to Aurora via the RDS Data API — no VPC needed.
    use_data_api: bool = False
    db_cluster_arn: str | None = None
    db_secret_arn: str | None = None
    aws_region: str = "us-east-1"

    # Direct connection. DATABASE_URL (a full SQLAlchemy URL) wins when set — the
    # Fargate migration task uses it. Otherwise the discrete fields below build a
    # local postgresql+psycopg URL for development.
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "courtside"
    db_user: str = "courtside"
    db_password: str = "courtside"

    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
