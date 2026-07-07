"""Request-time inference client for the next-game points model.

Follows the same key-gated fallback shape as `anthropic_client.py`: if no SageMaker
endpoint is configured we return the trailing-average baseline, so the API behaves
sensibly in local dev, tests, and any environment where the model isn't deployed.
The endpoint is invoked over `sagemaker-runtime` (boto3) — no model weights or ML
libraries are loaded in the Lambda process.
"""

from __future__ import annotations

from dataclasses import dataclass

from courtside.config import get_settings
from courtside.db.models import Game
from courtside.ml.baseline import trailing_average_points
from courtside.ml.features import to_vector

BASELINE_VERSION = "baseline-trailing-avg"


@dataclass
class PointsPrediction:
    predicted_points: float
    baseline_points: float
    model_version: str
    source: str  # "sagemaker" | "baseline"


def baseline_prediction(prior_games: list[Game]) -> PointsPrediction:
    baseline = round(trailing_average_points(prior_games), 1)
    return PointsPrediction(
        predicted_points=baseline,
        baseline_points=baseline,
        model_version=BASELINE_VERSION,
        source="baseline",
    )


def predict_points(features: dict[str, float], prior_games: list[Game]) -> PointsPrediction:
    settings = get_settings()
    if not settings.sagemaker_endpoint_name:
        return baseline_prediction(prior_games)

    predicted = _invoke_endpoint(settings.sagemaker_endpoint_name, features, settings.aws_region)
    return PointsPrediction(
        predicted_points=round(predicted, 1),
        baseline_points=round(trailing_average_points(prior_games), 1),
        model_version=settings.sagemaker_endpoint_name,
        source="sagemaker",
    )


def _invoke_endpoint(endpoint_name: str, features: dict[str, float], region: str) -> float:
    import boto3

    body = ",".join(str(v) for v in to_vector(features))
    client = boto3.client("sagemaker-runtime", region_name=region)
    response = client.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Accept="text/csv",
        Body=body.encode("utf-8"),
    )
    payload = response["Body"].read().decode("utf-8").strip()
    # XGBoost SageMaker containers return a single CSV scalar (or one per row).
    return float(payload.splitlines()[0].split(",")[0])
