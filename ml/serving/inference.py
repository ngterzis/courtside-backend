"""SageMaker XGBoost script-mode inference handlers.

Packaged with the model artifact (see train.py `source_dir`) and run inside the
SageMaker XGBoost container on the endpoint. Accepts a CSV feature row (the same
ordered vector the Lambda sends via `courtside.ml.client`) and returns the predicted
points as a CSV scalar.
"""

from __future__ import annotations

import os

import xgboost as xgb


def model_fn(model_dir: str) -> xgb.Booster:
    booster = xgb.Booster()
    booster.load_model(os.path.join(model_dir, "xgboost-model"))
    return booster


def input_fn(request_body: str, content_type: str = "text/csv") -> xgb.DMatrix:
    if content_type != "text/csv":
        raise ValueError(f"unsupported content type: {content_type}")
    rows = [
        [float(v) for v in line.split(",")]
        for line in request_body.strip().splitlines()
    ]
    return xgb.DMatrix(rows)


def predict_fn(data: xgb.DMatrix, model: xgb.Booster):
    return model.predict(data)


def output_fn(prediction, accept: str = "text/csv") -> str:
    return "\n".join(f"{p:.4f}" for p in prediction)
