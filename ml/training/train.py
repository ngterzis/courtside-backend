"""Launch a SageMaker training job for the next-game points regressor and register
the result if it beats the baseline.

Flow:
  1. Pull a leak-free training set from the Feature Store offline store (Athena).
  2. Time-ordered split (never shuffle — the target is the future).
  3. Upload train/test CSVs to S3 and run `train_script.py` as a SageMaker training
     job (script mode on the built-in XGBoost container). The instance is billed per
     second and terminates itself when the job ends — no idle cost.
  4. Inside the job, the script logs params/metrics/artifacts to the managed MLflow
     tracking server; the launcher reads the final metrics back from the job via
     `metric_definitions`.
  5. Only if the model beats the trailing-average baseline, register the job's
     model.tar.gz as a Model Package (pending approval) in the SageMaker Model
     Registry so `deploy_endpoint.py` can ship it.

    uv run --group ml python -m ml.training.train
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import boto3
import pandas as pd
import sagemaker
from sagemaker.xgboost.estimator import XGBoost
from sagemaker.xgboost.model import XGBoostModel

from courtside.ml.features import FEATURE_NAMES
from ml.config import PipelineConfig
from ml.feature_store.feature_group import _feature_group

TEST_FRACTION = 0.2
XGB_FRAMEWORK_VERSION = "1.7-1"
TRAIN_INSTANCE_TYPE = "ml.m5.large"

HYPERPARAMETERS = {
    "max_depth": 3,
    "eta": 0.1,
    "subsample": 0.8,
    "min_child_weight": 3,
    "num_round": 200,
}


def _load_training_frame(cfg: PipelineConfig) -> pd.DataFrame:
    fg = _feature_group(cfg)
    query = fg.athena_query()
    sql = (Path(__file__).parent.parent / "feature_store" / "training_query.sql").read_text()
    query.run(
        query_string=sql.format(table=query.table_name),
        output_location=cfg.athena_output_s3,
    )
    query.wait()
    return query.as_dataframe()


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("event_time").reset_index(drop=True)
    cut = int(len(df) * (1 - TEST_FRACTION))
    return df.iloc[:cut], df.iloc[cut:]


def _upload_split(
    session: sagemaker.Session, bucket: str, train_df: pd.DataFrame, test_df: pd.DataFrame
) -> tuple[str, str]:
    columns = ["label", *FEATURE_NAMES]
    tmp = Path(tempfile.mkdtemp())
    uris = []
    for name, df in (("train", train_df), ("test", test_df)):
        path = tmp / f"{name}.csv"
        df[columns].to_csv(path, index=False)
        uris.append(
            session.upload_data(str(path), bucket=bucket, key_prefix=f"training-input/{name}")
        )
    return uris[0], uris[1]


def train(cfg: PipelineConfig) -> None:
    df = _load_training_frame(cfg)
    if df.empty:
        raise RuntimeError("no training rows in the offline store yet — run ingest first")

    train_df, test_df = _time_split(df)

    boto_session = boto3.Session(region_name=cfg.region)
    session = sagemaker.Session(boto_session)
    bucket = cfg.offline_store_s3.removeprefix("s3://").split("/", 1)[0]
    train_uri, test_uri = _upload_split(session, bucket, train_df, test_df)

    estimator = XGBoost(
        entry_point="train_script.py",
        source_dir=str(Path(__file__).parent),
        framework_version=XGB_FRAMEWORK_VERSION,
        py_version="py3",
        role=cfg.role_arn,
        instance_type=TRAIN_INSTANCE_TYPE,
        instance_count=1,
        output_path=f"s3://{bucket}/training-jobs",
        base_job_name="next-game-points",
        hyperparameters=HYPERPARAMETERS,
        environment={"MLFLOW_TRACKING_URI": cfg.mlflow_tracking_uri},
        metric_definitions=[
            {"Name": "mae", "Regex": r"model_mae=([0-9.]+)"},
            {"Name": "rmse", "Regex": r"model_rmse=([0-9.]+)"},
            {"Name": "baseline_mae", "Regex": r"baseline_mae=([0-9.]+)"},
        ],
        sagemaker_session=session,
    )
    estimator.fit({"train": train_uri, "test": test_uri})

    job_name = estimator.latest_training_job.name
    desc = boto_session.client("sagemaker").describe_training_job(TrainingJobName=job_name)
    metrics = {m["MetricName"]: m["Value"] for m in desc.get("FinalMetricDataList", [])}
    if "mae" not in metrics or "baseline_mae" not in metrics:
        raise RuntimeError(f"training job {job_name} emitted no metrics: {metrics}")

    model_mae, baseline_mae = metrics["mae"], metrics["baseline_mae"]
    beats_baseline = model_mae < baseline_mae
    print(f"MAE {model_mae:.3f} vs baseline {baseline_mae:.3f} — "
          f"{'REGISTER' if beats_baseline else 'SKIP (does not beat baseline)'}")

    if beats_baseline:
        _register(cfg, session, estimator.model_data, model_mae, job_name)


def _register(
    cfg: PipelineConfig, session: sagemaker.Session, model_data: str, mae: float, job_name: str
) -> None:
    model = XGBoostModel(
        model_data=model_data,
        role=cfg.role_arn,
        entry_point="inference.py",
        source_dir=str(Path(__file__).parent.parent / "serving"),
        framework_version=XGB_FRAMEWORK_VERSION,
        sagemaker_session=session,
    )
    model.register(
        content_types=["text/csv"],
        response_types=["text/csv"],
        inference_instances=["ml.t2.medium"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=cfg.model_package_group,
        approval_status="PendingManualApproval",
        customer_metadata_properties={"mae": f"{mae:.4f}", "training_job_name": job_name},
    )
    print(f"registered model package in group {cfg.model_package_group}")


if __name__ == "__main__":
    train(PipelineConfig.from_env())
