"""rename fg_made/fg_attempted to fg2_made/fg2_attempted

Revision ID: 0002_rename_fg_columns
Revises: 0001_initial
Create Date: 2026-08-14 00:00:00

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_rename_fg_columns"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("games", "fg_made", new_column_name="fg2_made")
    op.alter_column("games", "fg_attempted", new_column_name="fg2_attempted")


def downgrade() -> None:
    op.alter_column("games", "fg2_made", new_column_name="fg_made")
    op.alter_column("games", "fg2_attempted", new_column_name="fg_attempted")
