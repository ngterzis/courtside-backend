"""Shared configuration for the offline pipeline, read from the environment.

Kept separate from `courtside.config` (the app settings) so the pipeline can be
configured independently in CI without importing FastAPI/serving concerns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The label value written for "current form" serving records that have no known
# outcome yet. Training queries filter these out.
UNLABELED = -1.0


@dataclass(frozen=True)
class PipelineConfig:
    region: str
    feature_group_name: str
    offline_store_s3: str  # s3://bucket/prefix for the offline store
    athena_output_s3: str  # s3://bucket/prefix for Athena query results
    role_arn: str  # SageMaker execution role
    mlflow_tracking_uri: str
    model_package_group: str
    endpoint_name: str
    pipeline_name: str

    @classmethod
    def from_env(cls) -> PipelineConfig:
        def req(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"missing required env var: {name}")
            return value

        return cls(
            region=os.environ.get("AWS_REGION", "eu-central-1"),
            feature_group_name=os.environ.get("FEATURE_GROUP_NAME", "courtside-player-form"),
            offline_store_s3=req("FEATURE_STORE_OFFLINE_S3"),
            athena_output_s3=req("ATHENA_OUTPUT_S3"),
            role_arn=req("SAGEMAKER_ROLE_ARN"),
            mlflow_tracking_uri=req("MLFLOW_TRACKING_URI"),
            model_package_group=os.environ.get("MODEL_PACKAGE_GROUP", "courtside-next-game-points"),
            endpoint_name=os.environ.get("ENDPOINT_NAME", "courtside-next-game-points"),
            pipeline_name=os.environ.get("PIPELINE_NAME", "courtside-next-game-points"),
        )
