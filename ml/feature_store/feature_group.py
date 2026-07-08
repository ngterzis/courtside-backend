"""Create (or describe) the SageMaker Feature Store feature group for player form.

Schema is derived from `courtside.ml.features.FEATURE_NAMES` so the feature group and
the code that computes features can never drift apart. Record identifier is a synthetic
`record_id` ("<player_id>#<event_date>"); event time drives point-in-time reads.

Usage:
    uv run --group ml python -m ml.feature_store.feature_group create
    uv run --group ml python -m ml.feature_store.feature_group describe
"""

from __future__ import annotations

import sys
import time

import boto3
import sagemaker
from sagemaker.feature_store.feature_definition import (
    FeatureDefinition,
    FeatureTypeEnum,
)
from sagemaker.feature_store.feature_group import FeatureGroup

from courtside.ml.features import FEATURE_NAMES
from ml.config import PipelineConfig


def _feature_definitions() -> list[FeatureDefinition]:
    definitions = [
        FeatureDefinition("record_id", FeatureTypeEnum.STRING),
        FeatureDefinition("player_id", FeatureTypeEnum.STRING),
        FeatureDefinition("event_time", FeatureTypeEnum.STRING),
        FeatureDefinition("label", FeatureTypeEnum.FRACTIONAL),
    ]
    definitions += [
        FeatureDefinition(name, FeatureTypeEnum.FRACTIONAL) for name in FEATURE_NAMES
    ]
    return definitions


def _feature_group(cfg: PipelineConfig) -> FeatureGroup:
    session = sagemaker.Session(boto3.Session(region_name=cfg.region))
    fg = FeatureGroup(name=cfg.feature_group_name, sagemaker_session=session)
    fg.feature_definitions = _feature_definitions()
    return fg


def create(cfg: PipelineConfig) -> None:
    fg = _feature_group(cfg)
    fg.create(
        s3_uri=cfg.offline_store_s3,
        record_identifier_name="record_id",
        event_time_feature_name="event_time",
        role_arn=cfg.role_arn,
        enable_online_store=True,
    )
    # Creation is async; poll until the group leaves "Creating".
    while fg.describe().get("FeatureGroupStatus") == "Creating":
        time.sleep(5)
    print("feature group status:", fg.describe().get("FeatureGroupStatus"))


def describe(cfg: PipelineConfig) -> None:
    print(_feature_group(cfg).describe())


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "describe"
    conf = PipelineConfig.from_env()
    {"create": create, "describe": describe}[action](conf)
