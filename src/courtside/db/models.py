from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _enum(enum_cls: type[StrEnum], length: int) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [m.value for m in members],
    )


class Position(StrEnum):
    GUARD = "Guard"
    FORWARD = "Forward"
    CENTER = "Center"


class HomeAway(StrEnum):
    HOME = "H"
    AWAY = "A"


class Result(StrEnum):
    WIN = "W"
    LOSS = "L"


class NotificationType(StrEnum):
    PERSONAL_BEST = "personal_best"
    STATS_READY = "stats_ready"
    COACH_NOTE = "coach_note"
    ARCHETYPE_CHANGED = "archetype_changed"
    WEEKLY_SUMMARY = "weekly_summary"


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    jersey_number: Mapped[int] = mapped_column(Integer)
    position: Mapped[Position] = mapped_column(_enum(Position, 20))
    onboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    player_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("players.id"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    label: Mapped[str] = mapped_column(String(60))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("players.id"), index=True)
    season_id: Mapped[UUID] = mapped_column(ForeignKey("seasons.id"), index=True)

    date: Mapped[date] = mapped_column(Date, index=True)
    opponent: Mapped[str] = mapped_column(String(120))
    home_away: Mapped[HomeAway] = mapped_column(_enum(HomeAway, 1))
    result: Mapped[Result] = mapped_column(_enum(Result, 1))
    team_score: Mapped[int] = mapped_column(Integer)
    opponent_score: Mapped[int] = mapped_column(Integer)

    points: Mapped[int] = mapped_column(Integer)
    rebounds: Mapped[int] = mapped_column(Integer)
    assists: Mapped[int] = mapped_column(Integer)
    steals: Mapped[int] = mapped_column(Integer)
    blocks: Mapped[int] = mapped_column(Integer)
    turnovers: Mapped[int] = mapped_column(Integer)
    fouls: Mapped[int] = mapped_column(Integer)
    fg_made: Mapped[int] = mapped_column(Integer)
    fg_attempted: Mapped[int] = mapped_column(Integer)
    three_made: Mapped[int] = mapped_column(Integer)
    three_attempted: Mapped[int] = mapped_column(Integer)
    ft_made: Mapped[int] = mapped_column(Integer)
    ft_attempted: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CoachNote(Base):
    __tablename__ = "coach_notes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id"), unique=True)
    author_name: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Archetype(Base):
    __tablename__ = "archetypes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("players.id"), index=True)
    season_id: Mapped[UUID] = mapped_column(ForeignKey("seasons.id"), index=True)

    primary_name: Mapped[str] = mapped_column(String(60))
    secondary_name: Mapped[str] = mapped_column(String(60))
    explanation: Mapped[str] = mapped_column(Text)
    receipt: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    scores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("player_id", "season_id", name="uq_archetypes_player_season"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("players.id"), index=True)
    type: Mapped[NotificationType] = mapped_column(_enum(NotificationType, 40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
