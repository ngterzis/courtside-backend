"""SageMaker Processing step: extracts metrics.json (written by train_script.py into
SM_MODEL_DIR, so it travels inside model.tar.gz) and re-emits it as a ProcessingOutput
so the pipeline's ConditionStep can gate registration on it via a PropertyFile —
PropertyFile/JsonGet only work off ProcessingStep outputs, not a training job's own
output directly.

Not meant to be run standalone outside the pipeline — see ml/pipeline.py.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

MODEL_INPUT_DIR = Path("/opt/ml/processing/model")
EVALUATION_OUTPUT_DIR = Path("/opt/ml/processing/output/evaluation")


def evaluate() -> None:
    archives = list(MODEL_INPUT_DIR.glob("*.tar.gz"))
    if not archives:
        raise RuntimeError(f"no model.tar.gz found in {MODEL_INPUT_DIR}")

    with tarfile.open(archives[0]) as tar:
        tar.extract("metrics.json", path=MODEL_INPUT_DIR, filter="data")
    metrics = json.loads((MODEL_INPUT_DIR / "metrics.json").read_text())

    EVALUATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_OUTPUT_DIR / "evaluation.json").write_text(json.dumps(metrics))
    print(f"model_mae={metrics['model_mae']:.6f} baseline_mae={metrics['baseline_mae']:.6f}")


if __name__ == "__main__":
    evaluate()
