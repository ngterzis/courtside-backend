"""rename games to game_performances, keep a games view for the previous release

Step 1 of 3 in splitting games into games + game_performances. Every row in
games is one player's line in one game, so the table is renamed rather than
copied: row ids, and coach_notes.game_id pointing at them, are unchanged.

The previous release still queries "games", so a plain view of the same name
stands in for it until step 2. A single-table SELECT * view is automatically
updatable, so that release's seed script can still insert and delete through it.

Revision ID: 0003_rename_games
Revises: 0002_rename_fg_columns
Create Date: 2026-10-19 00:00:00

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003_rename_games"
down_revision: str | None = "0002_rename_fg_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Index and primary key names share the schema namespace with tables, so they
# have to move off the games_* names before step 2 creates the new games table.
INDEXES = ("date", "player_id", "season_id", "team_id")
FOREIGN_KEYS = ("player_id", "season_id", "team_id")
CHECKS = ("home_away", "result")


def _rename_constraints(old: str, new: str) -> None:
    """Rename table `new`'s constraints and indexes from the `old` prefix."""
    op.execute(f"ALTER TABLE {new} RENAME CONSTRAINT {old}_pkey TO {new}_pkey")
    for col in INDEXES:
        op.execute(f"ALTER INDEX ix_{old}_{col} RENAME TO ix_{new}_{col}")
    for col in FOREIGN_KEYS:
        op.execute(
            f"ALTER TABLE {new} RENAME CONSTRAINT {old}_{col}_fkey TO {new}_{col}_fkey"
        )
    for col in CHECKS:
        op.execute(f"ALTER TABLE {new} RENAME CONSTRAINT ck_{old}_{col} TO ck_{new}_{col}")


def upgrade() -> None:
    op.rename_table("games", "game_performances")
    _rename_constraints("games", "game_performances")
    op.execute("CREATE VIEW games AS SELECT * FROM game_performances")


def downgrade() -> None:
    op.execute("DROP VIEW games")
    op.rename_table("game_performances", "games")
    _rename_constraints("game_performances", "games")
