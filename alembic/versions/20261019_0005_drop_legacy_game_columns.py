"""drop the game-level columns from game_performances and coach_notes.game_id

Step 3 of 3 in splitting games into games + game_performances. The step 2
release reads game facts through games and coach notes through
performance_id, so the copies kept for the step 1 release can go, and the new
links become required. Dropping the columns also drops their indexes, foreign
keys and check constraints.

Revision ID: 0005_drop_legacy_game_columns
Revises: 0004_create_games
Create Date: 2026-10-19 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_drop_legacy_game_columns"
down_revision: str | None = "0004_create_games"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_COLUMNS = (
    "team_id",
    "season_id",
    "date",
    "opponent",
    "home_away",
    "result",
    "team_score",
    "opponent_score",
)


def upgrade() -> None:
    op.alter_column("game_performances", "game_id", nullable=False)
    for col in LEGACY_COLUMNS:
        op.drop_column("game_performances", col)

    op.alter_column("coach_notes", "performance_id", nullable=False)
    op.drop_column("coach_notes", "game_id")


def downgrade() -> None:
    # Back to the step 2 shape: the copies return backfilled but nullable.
    op.add_column(
        "coach_notes",
        sa.Column("game_id", sa.Uuid(), sa.ForeignKey("game_performances.id"), nullable=True),
    )
    op.execute("UPDATE coach_notes SET game_id = performance_id")
    op.create_index("ix_coach_notes_game_id", "coach_notes", ["game_id"], unique=True)
    op.alter_column("coach_notes", "performance_id", nullable=True)

    op.add_column(
        "game_performances",
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=True),
    )
    op.add_column(
        "game_performances",
        sa.Column("season_id", sa.Uuid(), sa.ForeignKey("seasons.id"), nullable=True),
    )
    op.add_column("game_performances", sa.Column("date", sa.Date(), nullable=True))
    op.add_column("game_performances", sa.Column("opponent", sa.String(120), nullable=True))
    op.add_column("game_performances", sa.Column("home_away", sa.String(1), nullable=True))
    op.add_column("game_performances", sa.Column("result", sa.String(1), nullable=True))
    op.add_column("game_performances", sa.Column("team_score", sa.Integer(), nullable=True))
    op.add_column(
        "game_performances", sa.Column("opponent_score", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_game_performances_home_away", "game_performances", "home_away IN ('H', 'A')"
    )
    op.create_check_constraint(
        "ck_game_performances_result", "game_performances", "result IN ('W', 'L')"
    )
    for col in ("team_id", "season_id", "date"):
        op.create_index(f"ix_game_performances_{col}", "game_performances", [col])
    op.execute(
        """
        UPDATE game_performances gp
        SET team_id = s.team_id, season_id = g.season_id, date = g.date,
            opponent = g.opponent, home_away = g.home_away, result = g.result,
            team_score = g.team_score, opponent_score = g.opponent_score
        FROM games g JOIN seasons s ON s.id = g.season_id
        WHERE g.id = gp.game_id
        """
    )
    op.alter_column("game_performances", "game_id", nullable=True)
