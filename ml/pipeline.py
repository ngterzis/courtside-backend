"""Defines the SageMaker Pipeline that automates the ingest → prepare → train →
(conditionally) register loop, and exposes a small CLI to keep it in sync.

    Ingest (ProcessingStep) → PrepareData (ProcessingStep) → Train (TrainingStep)
        → Evaluate (ProcessingStep) → Condition(model_mae < baseline_mae)
        → Register (ModelStep, PendingManualApproval)

Ingest/PrepareData/Evaluate run on the custom image built from Dockerfile.ml (the
`ml` uv group is deliberately excluded from the serving Lambda image, so those steps
need their own image). Train reuses the same built-in-XGBoost script-mode container
`train_script.py` always has. Approving a registered model and deploying it stays a
fully manual step — see ml/serving/deploy_endpoint.py — this pipeline never deploys.

Runs are on-demand only, nothing here schedules them:

    uv run --group ml python -m ml.pipeline run

To create or update the pipeline definition after changing this file (also done by
CI on every push that touches ml/** — see .github/workflows/ml-pipeline.yml):

    uv run --group ml python -m ml.pipeline upsert
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from sagemaker.inputs import TrainingInput
from sagemaker.processing import ProcessingInput, ProcessingOutput, Processor
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.conditions import ConditionLessThan
from sagemaker.workflow.functions import JsonGet
from sagemaker.workflow.model_step import ModelStep
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.steps import ProcessingStep, TrainingStep
from sagemaker.xgboost.estimator import XGBoost
from sagemaker.xgboost.model import XGBoostModel

from ml.config import PipelineConfig

XGB_FRAMEWORK_VERSION = "1.7-1"
TRAIN_INSTANCE_TYPE = "ml.m5.large"
PROCESSING_INSTANCE_TYPE = "ml.m5.large"

HYPERPARAMETERS = {
    "max_depth": 3,
    "eta": 0.1,
    "subsample": 0.8,
    "min_child_weight": 3,
    "num_round": 200,
}


def _pipeline_env(cfg: PipelineConfig) -> dict[str, str]:
    return {
        "AWS_REGION": cfg.region,
        "FEATURE_GROUP_NAME": cfg.feature_group_name,
        "FEATURE_STORE_OFFLINE_S3": cfg.offline_store_s3,
        "ATHENA_OUTPUT_S3": cfg.athena_output_s3,
        "SAGEMAKER_ROLE_ARN": cfg.role_arn,
        "MLFLOW_TRACKING_URI": cfg.mlflow_tracking_uri,
        "MODEL_PACKAGE_GROUP": cfg.model_package_group,
        "ENDPOINT_NAME": cfg.endpoint_name,
        "PIPELINE_NAME": cfg.pipeline_name,
    }


def _ingest_env(cfg: PipelineConfig) -> dict[str, str]:
    def req(name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"missing required env var: {name}")
        return value

    # ingest.py reads games via courtside.db (RDS Data API — no VPC needed), on top
    # of the ml.config env every step gets.
    return {
        **_pipeline_env(cfg),
        "USE_DATA_API": "true",
        "DB_CLUSTER_ARN": req("DB_CLUSTER_ARN"),
        "DB_SECRET_ARN": req("DB_SECRET_ARN"),
    }


def build(cfg: PipelineConfig, image_uri: str) -> Pipeline:
    bucket = cfg.offline_store_s3.removeprefix("s3://").split("/", 1)[0]
    # default_bucket pinned to our own bucket: otherwise the SDK probes/creates its
    # own auto-named "sagemaker-<region>-<account>" bucket on every session, which
    # neither IAM role here (sagemaker_exec, github_actions) was ever granted access
    # to — only courtside-prod-ml-* is.
    session = PipelineSession(
        boto_session=boto3.Session(region_name=cfg.region), default_bucket=bucket
    )

    # ── Ingest ───────────────────────────────────────────────────────────────
    ingest_processor = Processor(
        image_uri=image_uri,
        role=cfg.role_arn,
        instance_type=PROCESSING_INSTANCE_TYPE,
        instance_count=1,
        entrypoint=["python3", "-m", "ml.feature_store.ingest"],
        env=_ingest_env(cfg),
        sagemaker_session=session,
    )
    ingest_step = ProcessingStep(name="Ingest", step_args=ingest_processor.run())

    # ── PrepareData ──────────────────────────────────────────────────────────
    # No data flows from Ingest to PrepareData through the SDK (Ingest writes to the
    # Feature Store, not to a file PrepareData reads as input) so the dependency has
    # to be declared explicitly.
    prepare_processor = Processor(
        image_uri=image_uri,
        role=cfg.role_arn,
        instance_type=PROCESSING_INSTANCE_TYPE,
        instance_count=1,
        entrypoint=["python3", "-m", "ml.training.prepare_data"],
        env=_pipeline_env(cfg),
        sagemaker_session=session,
    )
    prepare_step = ProcessingStep(
        name="PrepareData",
        step_args=prepare_processor.run(
            outputs=[
                ProcessingOutput(output_name="train", source="/opt/ml/processing/output/train"),
                ProcessingOutput(output_name="test", source="/opt/ml/processing/output/test"),
            ],
        ),
        depends_on=[ingest_step],
    )

    # ── Train ────────────────────────────────────────────────────────────────
    estimator = XGBoost(
        entry_point="train_script.py",
        source_dir=str(Path(__file__).parent / "training"),
        framework_version=XGB_FRAMEWORK_VERSION,
        py_version="py3",
        role=cfg.role_arn,
        instance_type=TRAIN_INSTANCE_TYPE,
        instance_count=1,
        output_path=f"s3://{bucket}/training-jobs",
        base_job_name="next-game-points",
        hyperparameters=HYPERPARAMETERS,
        environment={"MLFLOW_TRACKING_URI": cfg.mlflow_tracking_uri},
        sagemaker_session=session,
    )
    prepare_outputs = prepare_step.properties.ProcessingOutputConfig.Outputs
    train_step = TrainingStep(
        name="Train",
        step_args=estimator.fit(
            {
                "train": TrainingInput(s3_data=prepare_outputs["train"].S3Output.S3Uri),
                "test": TrainingInput(s3_data=prepare_outputs["test"].S3Output.S3Uri),
            }
        ),
    )

    # ── Evaluate ─────────────────────────────────────────────────────────────
    # Extracts metrics.json (bundled into model.tar.gz by train_script.py) as its own
    # ProcessingOutput — PropertyFile/JsonGet only work off ProcessingStep outputs.
    evaluate_processor = Processor(
        image_uri=image_uri,
        role=cfg.role_arn,
        instance_type=PROCESSING_INSTANCE_TYPE,
        instance_count=1,
        entrypoint=["python3", "-m", "ml.training.evaluate"],
        sagemaker_session=session,
    )
    evaluation_property_file = PropertyFile(
        name="EvaluationReport", output_name="evaluation", path="evaluation.json"
    )
    evaluate_step = ProcessingStep(
        name="Evaluate",
        step_args=evaluate_processor.run(
            inputs=[
                ProcessingInput(
                    source=train_step.properties.ModelArtifacts.S3ModelArtifacts,
                    destination="/opt/ml/processing/model",
                ),
            ],
            outputs=[
                ProcessingOutput(
                    output_name="evaluation", source="/opt/ml/processing/output/evaluation"
                ),
            ],
        ),
        property_files=[evaluation_property_file],
    )

    # ── Condition + Register ─────────────────────────────────────────────────
    model = XGBoostModel(
        model_data=train_step.properties.ModelArtifacts.S3ModelArtifacts,
        role=cfg.role_arn,
        entry_point="inference.py",
        source_dir=str(Path(__file__).parent / "serving"),
        framework_version=XGB_FRAMEWORK_VERSION,
        sagemaker_session=session,
    )
    register_step = ModelStep(
        name="Register",
        step_args=model.register(
            content_types=["text/csv"],
            response_types=["text/csv"],
            inference_instances=["ml.t2.medium"],
            transform_instances=["ml.m5.large"],
            model_package_group_name=cfg.model_package_group,
            approval_status="PendingManualApproval",
        ),
    )
    condition_step = ConditionStep(
        name="BeatsBaseline",
        conditions=[
            ConditionLessThan(
                left=JsonGet(
                    step_name=evaluate_step.name,
                    property_file=evaluation_property_file,
                    json_path="model_mae",
                ),
                right=JsonGet(
                    step_name=evaluate_step.name,
                    property_file=evaluation_property_file,
                    json_path="baseline_mae",
                ),
            )
        ],
        if_steps=[register_step],
        else_steps=[],
    )

    return Pipeline(
        name=cfg.pipeline_name,
        steps=[ingest_step, prepare_step, train_step, evaluate_step, condition_step],
        sagemaker_session=session,
    )


def upsert(cfg: PipelineConfig, image_uri: str) -> None:
    pipeline = build(cfg, image_uri)
    pipeline.upsert(role_arn=cfg.role_arn)
    print(f"upserted pipeline {cfg.pipeline_name}")


def run(cfg: PipelineConfig, image_uri: str) -> None:
    pipeline = build(cfg, image_uri)
    execution = pipeline.start()
    print(f"started execution {execution.arn}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upsert"
    conf = PipelineConfig.from_env()
    uri = os.environ.get("ML_PIPELINE_IMAGE_URI")
    if not uri:
        raise RuntimeError("missing required env var: ML_PIPELINE_IMAGE_URI")
    {"upsert": upsert, "run": run}[action](conf, uri)
