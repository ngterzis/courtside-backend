"""predictions table

Revision ID: 0002_predictions
Revises: 0001_initial
Create Date: 2026-07-01 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_predictions"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("predicted_points", sa.Float(), nullable=False),
        sa.Column("baseline_points", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_predictions_team_id", "predictions", ["team_id"])
    op.create_index("ix_predictions_player_id", "predictions", ["player_id"])
    op.create_index("ix_predictions_as_of_date", "predictions", ["as_of_date"])


def downgrade() -> None:
    op.drop_table("predictions")
