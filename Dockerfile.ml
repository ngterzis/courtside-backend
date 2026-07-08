# syntax=docker/dockerfile:1

# Image for the SageMaker Pipeline's Ingest and PrepareData Processing steps. Kept
# separate from the main Dockerfile because the `ml` uv group (sagemaker, xgboost,
# mlflow, pandas) is deliberately excluded from the serving Lambda image.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer — cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --group ml --no-dev --no-install-project

# Application code (courtside.ml.features etc.) + the pipeline scripts themselves.
COPY src ./src
COPY ml ./ml
RUN uv sync --frozen --group ml --no-dev

# SageMaker's Processor sets its own entrypoint/command at run time
# (ml/pipeline.py), so this default only matters for local `docker run` testing.
CMD ["python3", "-m", "ml.feature_store.ingest"]
