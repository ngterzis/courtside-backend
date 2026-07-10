"""Compute feature records from the games table and PutRecord them into Feature Store.

Two kinds of records are written, both using the shared point-in-time feature code:

* **Training records** — one per historical (player, game) with enough prior form, each
  carrying the actual points as `label`. These land in the offline store for training.
* **Current-form records** — one per player as of "now" (their next, unplayed game),
  written with `label = UNLABELED` and read back at serve time via `GetRecord`.

Run after each ingest of new games:
    uv run --group ml python -m ml.feature_store.ingest
"""

from __future__ import annotations

from datetime import UTC, datetime

import boto3
import sagemaker
from sagemaker.feature_store.feature_group import FeatureGroup
from sqlalchemy import select

from courtside.db.models import Game, Season
from courtside.db.session import get_session_factory
from courtside.ml.features import (
    FEATURE_NAMES,
    MIN_HISTORY,
    build_training_examples,
    latest_features,
)
from ml.config import UNLABELED, PipelineConfig


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(record_id: str, player_id: str, event_time: str, label: float,
            features: dict[str, float]) -> list[dict[str, str]]:
    values = {
        "record_id": record_id,
        "player_id": player_id,
        "event_time": event_time,
        "label": str(label),
        **{name: str(features[name]) for name in FEATURE_NAMES},
    }
    return [{"FeatureName": k, "ValueAsString": v} for k, v in values.items()]


def _load_games_by_player() -> tuple[dict[str, list[Game]], dict[str, list[Game]]]:
    """Return (all games by player, active-season games by player)."""
    factory = get_session_factory()
    with factory() as db:
        active_season_ids = set(
            db.scalars(select(Season.id).where(Season.end_date.is_(None))).all()
        )
        games = list(db.scalars(select(Game)).all())

    all_by_player: dict[str, list[Game]] = {}
    active_by_player: dict[str, list[Game]] = {}
    for g in games:
        # str(), not .hex: the RDS Data API (used here) returns UUID columns as
        # plain strings rather than uuid.UUID objects, so .hex isn't available —
        # see the same note in courtside/db/session.py. str() also works on a real
        # UUID object (direct psycopg path, e.g. local dev), giving the same
        # canonical dashed form either way.
        all_by_player.setdefault(str(g.player_id), []).append(g)
        if g.season_id in active_season_ids:
            active_by_player.setdefault(str(g.player_id), []).append(g)
    return all_by_player, active_by_player


def ingest(cfg: PipelineConfig) -> None:
    session = sagemaker.Session(boto3.Session(region_name=cfg.region))
    fg = FeatureGroup(name=cfg.feature_group_name, sagemaker_session=session)

    all_by_player, active_by_player = _load_games_by_player()

    training = build_training_examples(all_by_player)
    for ex in training:
        record_id = f"{ex.player_id}#{ex.event_date}"
        fg.put_record(_record(record_id, ex.player_id, f"{ex.event_date}T00:00:00Z",
                              ex.label, ex.features))

    now = _now_iso()
    current = 0
    for player_id, games in active_by_player.items():
        if len(games) < MIN_HISTORY:
            continue
        last = max(games, key=lambda g: g.date)
        days_rest = (datetime.now(UTC).date() - last.date).days
        features = latest_features(games, is_home=1, days_rest=days_rest)
        fg.put_record(_record(f"{player_id}#current", player_id, now, UNLABELED, features))
        current += 1

    print(f"ingested {len(training)} training records, {current} current-form records")


if __name__ == "__main__":
    ingest(PipelineConfig.from_env())
