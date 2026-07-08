"""Entry point executed inside the SageMaker XGBoost training container.

Script mode: the container pip-installs `requirements.txt` from this directory,
passes hyperparameters as CLI flags, mounts the S3 channels under
/opt/ml/input/data/<channel>, and tars everything written to SM_MODEL_DIR into
model.tar.gz when the job exits (the same layout inference.py's model_fn expects).

Not meant to be run locally — train.py launches the job.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error


def _read_channel(channel: str) -> pd.DataFrame:
    directory = Path(os.environ[f"SM_CHANNEL_{channel.upper()}"])
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise RuntimeError(f"no csv files in channel {channel}: {directory}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_depth", type=int, default=3)
    parser.add_argument("--eta", type=float, default=0.1)
    parser.add_argument("--subsample", type=float, default=0.8)
    parser.add_argument("--min_child_weight", type=int, default=3)
    parser.add_argument("--num_round", type=int, default=200)
    args = parser.parse_args()

    train_df = _read_channel("train")
    test_df = _read_channel("test")
    feature_names = [c for c in train_df.columns if c != "label"]

    params = {
        "objective": "reg:squarederror",
        "max_depth": args.max_depth,
        "eta": args.eta,
        "subsample": args.subsample,
        "min_child_weight": args.min_child_weight,
    }
    dtrain = xgb.DMatrix(train_df[feature_names], label=train_df["label"])
    dtest = xgb.DMatrix(test_df[feature_names], label=test_df["label"])

    job_name = json.loads(os.environ.get("SM_TRAINING_ENV", "{}")).get("job_name")

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment("next-game-points")

    with mlflow.start_run(run_name=job_name):
        mlflow.log_params(
            {**params, "num_round": args.num_round, "n_train": len(train_df)}
        )

        booster = xgb.train(params, dtrain, num_boost_round=args.num_round)

        preds = booster.predict(dtest)
        model_mae = mean_absolute_error(test_df["label"], preds)
        model_rmse = mean_squared_error(test_df["label"], preds) ** 0.5
        # Baseline = the trailing-3 average, already computed as a feature.
        baseline_mae = mean_absolute_error(test_df["label"], test_df["pts_avg_3"])

        mlflow.log_metrics(
            {"mae": model_mae, "rmse": model_rmse, "baseline_mae": baseline_mae}
        )
        mlflow.xgboost.log_model(booster, artifact_path="model")
        mlflow.set_tag("beats_baseline", str(model_mae < baseline_mae))

    # Parsed from the job log by the launcher via metric_definitions regexes.
    print(f"model_mae={model_mae:.6f}")
    print(f"model_rmse={model_rmse:.6f}")
    print(f"baseline_mae={baseline_mae:.6f}")

    booster.save_model(os.path.join(os.environ["SM_MODEL_DIR"], "xgboost-model"))


if __name__ == "__main__":
    main()
