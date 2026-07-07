"""Offline ML pipeline for the next-game points model (runs in CI / Fargate, not Lambda).

Everything here imports feature logic from the installed `courtside.ml` package so the
training path and the request-time serving path compute features identically. Heavy
dependencies (sagemaker, mlflow, xgboost, awswrangler) live in the `ml` uv dependency
group and are intentionally kept out of the serving Lambda image.

Run modules from the repo root, e.g.:
    uv run --group ml python -m ml.feature_store.ingest
    uv run --group ml python -m ml.training.train
    uv run --group ml python -m ml.serving.deploy_endpoint
"""
