"""SageMaker Processing step: builds a leak-free train/test split from the Feature
Store offline store and writes it where ml/pipeline.py's ProcessingOutputs expect it
(consumed as TrainingInputs by the Train step).

Not meant to be run standalone outside the pipeline — see ml/pipeline.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from courtside.ml.features import FEATURE_NAMES
from ml.config import PipelineConfig
from ml.feature_store.feature_group import _feature_group

TEST_FRACTION = 0.2

TRAIN_OUTPUT_DIR = Path("/opt/ml/processing/output/train")
TEST_OUTPUT_DIR = Path("/opt/ml/processing/output/test")


def _load_training_frame(cfg: PipelineConfig) -> pd.DataFrame:
    fg = _feature_group(cfg)
    query = fg.athena_query()
    sql = (Path(__file__).parent.parent / "feature_store" / "training_query.sql").read_text()
    query.run(
        query_string=sql.format(table=query.table_name),
        output_location=cfg.athena_output_s3,
        workgroup=cfg.athena_workgroup,
    )
    query.wait()
    return query.as_dataframe()


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("event_time").reset_index(drop=True)
    cut = int(len(df) * (1 - TEST_FRACTION))
    return df.iloc[:cut], df.iloc[cut:]


def prepare(cfg: PipelineConfig) -> None:
    df = _load_training_frame(cfg)
    if df.empty:
        raise RuntimeError("no training rows in the offline store yet — run ingest first")

    train_df, test_df = _time_split(df)
    columns = ["label", *FEATURE_NAMES]

    TRAIN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    train_df[columns].to_csv(TRAIN_OUTPUT_DIR / "train.csv", index=False)
    test_df[columns].to_csv(TEST_OUTPUT_DIR / "test.csv", index=False)
    print(f"wrote {len(train_df)} train rows, {len(test_df)} test rows")


if __name__ == "__main__":
    prepare(PipelineConfig.from_env())
