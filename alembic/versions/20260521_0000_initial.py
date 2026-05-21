"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-21 00:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("jersey_number", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(20), nullable=False),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position IN ('Guard', 'Forward', 'Center')", name="ck_players_position"
        ),
    )
    op.create_index("ix_players_team_id", "players", ["team_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_player_id", "users", ["player_id"], unique=True)

    op.create_table(
        "seasons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_seasons_team_id", "seasons", ["team_id"])

    op.create_table(
        "games",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("season_id", sa.Uuid(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("opponent", sa.String(120), nullable=False),
        sa.Column("home_away", sa.String(1), nullable=False),
        sa.Column("result", sa.String(1), nullable=False),
        sa.Column("team_score", sa.Integer(), nullable=False),
        sa.Column("opponent_score", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("rebounds", sa.Integer(), nullable=False),
        sa.Column("assists", sa.Integer(), nullable=False),
        sa.Column("steals", sa.Integer(), nullable=False),
        sa.Column("blocks", sa.Integer(), nullable=False),
        sa.Column("turnovers", sa.Integer(), nullable=False),
        sa.Column("fouls", sa.Integer(), nullable=False),
        sa.Column("fg_made", sa.Integer(), nullable=False),
        sa.Column("fg_attempted", sa.Integer(), nullable=False),
        sa.Column("three_made", sa.Integer(), nullable=False),
        sa.Column("three_attempted", sa.Integer(), nullable=False),
        sa.Column("ft_made", sa.Integer(), nullable=False),
        sa.Column("ft_attempted", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("home_away IN ('H', 'A')", name="ck_games_home_away"),
        sa.CheckConstraint("result IN ('W', 'L')", name="ck_games_result"),
    )
    op.create_index("ix_games_team_id", "games", ["team_id"])
    op.create_index("ix_games_player_id", "games", ["player_id"])
    op.create_index("ix_games_season_id", "games", ["season_id"])
    op.create_index("ix_games_date", "games", ["date"])

    op.create_table(
        "coach_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("game_id", sa.Uuid(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("author_name", sa.String(120), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_coach_notes_team_id", "coach_notes", ["team_id"])
    op.create_index("ix_coach_notes_game_id", "coach_notes", ["game_id"], unique=True)

    op.create_table(
        "archetypes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("season_id", sa.Uuid(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("primary_name", sa.String(60), nullable=False),
        sa.Column("secondary_name", sa.String(60), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("receipt", postgresql.JSONB(), nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "player_id", "season_id", name="uq_archetypes_player_season"
        ),
    )
    op.create_index("ix_archetypes_team_id", "archetypes", ["team_id"])
    op.create_index("ix_archetypes_player_id", "archetypes", ["player_id"])
    op.create_index("ix_archetypes_season_id", "archetypes", ["season_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('personal_best', 'stats_ready', 'coach_note', "
            "'archetype_changed', 'weekly_summary')",
            name="ck_notifications_type",
        ),
    )
    op.create_index("ix_notifications_team_id", "notifications", ["team_id"])
    op.create_index("ix_notifications_player_id", "notifications", ["player_id"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("archetypes")
    op.drop_table("coach_notes")
    op.drop_table("games")
    op.drop_table("seasons")
    op.drop_table("users")
    op.drop_table("players")
    op.drop_table("teams")
