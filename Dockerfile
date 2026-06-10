# syntax=docker/dockerfile:1

# Lambda Web Adapter — runs the unmodified FastAPI/uvicorn app inside Lambda.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 AS adapter

FROM python:3.12-slim

# The adapter is auto-discovered by the Lambda runtime when placed here.
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer — cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + migrations.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

EXPOSE 8000

# API and chat Lambdas serve the web app; the migration ECS task overrides this
# command with `alembic upgrade head`.
CMD ["uvicorn", "courtside.main:app", "--host", "0.0.0.0", "--port", "8000"]
