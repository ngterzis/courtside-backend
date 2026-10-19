"""create games, link game_performances and coach_notes to their new parents

Step 2 of 3 in splitting games into games + game_performances. Builds one games
row per (season, date, opponent) from the per-player rows, points every
performance at its game, and gives coach_notes a performance_id. A game's team
is its season's team, so games has no team_id of its own.

The previous release (step 1) still reads the game-level columns on
game_performances and coach_notes.game_id, so they stay and are backfilled
here; they only become nullable, because this release stops writing them.
Step 3 drops them.

Revision ID: 0004_create_games
Revises: 0003_rename_games
Create Date: 2026-10-19 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_create_games"
down_revision: str | None = "0003_rename_games"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The game-level columns duplicated on every game_performances row.
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


def _check_game_facts_agree() -> None:
    """Fail before changing anything if players' rows disagree about a game.

    Picking one version silently would lose data; these need fixing by hand.
    """
    conflicts = op.get_bind().execute(
        sa.text(
            """
            SELECT season_id, date, opponent
            FROM game_performances
            GROUP BY season_id, date, opponent
            HAVING count(DISTINCT (home_away, result, team_score, opponent_score)) > 1
            """
        )
    ).fetchall()
    if conflicts:
        listed = ", ".join(f"{r.date} vs {r.opponent} (season {r.season_id})" for r in conflicts)
        raise RuntimeError(f"Player rows disagree on game-level facts for: {listed}")


def upgrade() -> None:
    _check_game_facts_agree()
    op.execute("DROP VIEW games")

    op.create_table(
        "games",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("season_id", sa.Uuid(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("opponent", sa.String(120), nullable=False),
        sa.Column("home_away", sa.String(1), nullable=False),
        sa.Column("result", sa.String(1), nullable=False),
        sa.Column("team_score", sa.Integer(), nullable=False),
        sa.Column("opponent_score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("home_away IN ('H', 'A')", name="ck_games_home_away"),
        sa.CheckConstraint("result IN ('W', 'L')", name="ck_games_result"),
        sa.UniqueConstraint(
            "season_id", "date", "opponent", name="uq_games_season_date_opponent"
        ),
    )
    op.create_index("ix_games_season_id", "games", ["season_id"])
    op.create_index("ix_games_date", "games", ["date"])

    op.execute(
        """
        INSERT INTO games (id, season_id, date, opponent, home_away, result,
                           team_score, opponent_score, created_at)
        SELECT gen_random_uuid(), season_id, date, opponent, home_away, result,
               team_score, opponent_score, min(created_at)
        FROM game_performances
        GROUP BY season_id, date, opponent, home_away, result, team_score, opponent_score
        """
    )

    op.add_column(
        "game_performances",
        sa.Column("game_id", sa.Uuid(), sa.ForeignKey("games.id"), nullable=True),
    )
    op.execute(
        """
        UPDATE game_performances gp SET game_id = g.id
        FROM games g
        WHERE g.season_id = gp.season_id AND g.date = gp.date AND g.opponent = gp.opponent
        """
    )
    op.create_index("ix_game_performances_game_id", "game_performances", ["game_id"])
    op.create_unique_constraint(
        "uq_game_performances_game_player", "game_performances", ["game_id", "player_id"]
    )
    for col in LEGACY_COLUMNS:
        op.alter_column("game_performances", col, nullable=True)

    op.add_column(
        "coach_notes",
        sa.Column(
            "performance_id",
            sa.Uuid(),
            sa.ForeignKey("game_performances.id"),
            nullable=True,
        ),
    )
    op.execute("UPDATE coach_notes SET performance_id = game_id")
    op.create_index(
        "ix_coach_notes_performance_id", "coach_notes", ["performance_id"], unique=True
    )
    op.alter_column("coach_notes", "game_id", nullable=True)


def downgrade() -> None:
    # Rows written by this release only have the new columns; copy them back.
    op.execute("UPDATE coach_notes SET game_id = performance_id WHERE game_id IS NULL")
    op.alter_column("coach_notes", "game_id", nullable=False)
    op.drop_index("ix_coach_notes_performance_id", table_name="coach_notes")
    op.drop_column("coach_notes", "performance_id")

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
    for col in LEGACY_COLUMNS:
        op.alter_column("game_performances", col, nullable=False)
    op.drop_constraint(
        "uq_game_performances_game_player", "game_performances", type_="unique"
    )
    op.drop_index("ix_game_performances_game_id", table_name="game_performances")
    op.drop_column("game_performances", "game_id")

    op.drop_table("games")
    op.execute("CREATE VIEW games AS SELECT * FROM game_performances")
