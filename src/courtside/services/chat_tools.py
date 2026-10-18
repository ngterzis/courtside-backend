"""Read-only database tools the chat model can call.

Every tool is scoped to the authenticated player: the executor receives the
Player from the request, and no tool accepts a player id. That keeps the
"never name or compare teammates" rule enforced in code, not just in the
prompt — a prompt-injected "show me player X" has nothing to bind to.

Tool definitions are generated from the Pydantic input models below, so the
schema the model sees and the validation the executor runs never drift apart.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import CoachNote, Game, HomeAway, Player, Result, Season
from courtside.services.stats import (
    RAW_STAT_FIELDS,
    derived_stats,
    personal_bests,
    season_averages,
)

MAX_GAMES = 25

_PCT_FIELDS = ("fg_pct", "three_pct", "ft_pct", "ts_pct")
SortField = Literal[
    "date",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "fouls",
    "fg2_made",
    "fg2_attempted",
    "three_made",
    "three_attempted",
    "ft_made",
    "ft_attempted",
    "fg_pct",
    "three_pct",
    "ft_pct",
    "ts_pct",
]


class ToolInputError(Exception):
    """A tool call the model can fix: bad arguments or a lookup that found nothing."""


# --------------------------------------------------------------------------- #
# Input models
# --------------------------------------------------------------------------- #


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListSeasonsInput(_Input):
    pass


class SeasonSummaryInput(_Input):
    season_id: UUID | None = Field(
        default=None,
        description="Season to summarise (from list_seasons). Omit for the active season.",
    )


class FindGamesInput(_Input):
    season_id: UUID | Literal["all"] | None = Field(
        default=None,
        description=(
            "Season to search (from list_seasons), or 'all' for every season. "
            "Omit for the active season."
        ),
    )
    opponent: str | None = Field(
        default=None,
        max_length=120,
        description="Case-insensitive substring of the opponent's name.",
    )
    date_from: date | None = Field(default=None, description="Earliest game date, inclusive.")
    date_to: date | None = Field(default=None, description="Latest game date, inclusive.")
    result: Literal["W", "L"] | None = Field(default=None, description="Only wins or losses.")
    home_away: Literal["H", "A"] | None = Field(
        default=None, description="Only home (H) or away (A) games."
    )
    sort_by: SortField = Field(
        default="date", description="Field to sort by. Percentages are true shooting / FG / etc."
    )
    order: Literal["asc", "desc"] = Field(default="desc")
    limit: int = Field(default=10, ge=1, le=MAX_GAMES, description="Max games to return.")


class GetGameInput(_Input):
    game_id: UUID | None = Field(default=None, description="Game id from find_games.")
    # Annotated via the module: a field named `date` shadows the `date` type here.
    date: dt.date | None = Field(default=None, description="Game date, if the id is unknown.")

    @model_validator(mode="after")
    def _one_of(self) -> GetGameInput:
        if (self.game_id is None) == (self.date is None):
            raise ValueError("pass exactly one of game_id or date")
        return self


class SplitAveragesInput(_Input):
    group_by: Literal["home_away", "result", "opponent", "month"] = Field(
        description="How to split the player's games."
    )
    season_id: UUID | Literal["all"] | None = Field(
        default=None,
        description="Season (from list_seasons), or 'all'. Omit for the active season.",
    )
    last_n_games: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description="Only use the player's most recent N games before splitting.",
    )


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def _round_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Round averages to one decimal and express percentages as 0-100."""
    out: dict[str, Any] = {}
    for key, value in stats.items():
        if key in _PCT_FIELDS:
            out[key] = round(value * 100, 1)
        elif isinstance(value, float):
            out[key] = round(value, 1)
        else:
            out[key] = value
    return out


def _averages(games: list[Game], season_id: UUID | None = None) -> dict[str, Any]:
    stats = season_averages(games, season_id)  # type: ignore[arg-type]
    stats.pop("season_id", None)
    return _round_stats(stats)


def _game_row(game: Game) -> dict[str, Any]:
    d = derived_stats(game)
    return {
        "game_id": str(game.id),
        "date": game.date.isoformat(),
        "opponent": game.opponent,
        "home_away": game.home_away.value,
        "result": game.result.value,
        "score": f"{game.team_score}-{game.opponent_score}",
        "points": game.points,
        "rebounds": game.rebounds,
        "assists": game.assists,
        "steals": game.steals,
        "blocks": game.blocks,
        "turnovers": game.turnovers,
        "fouls": game.fouls,
        # Makes and attempts, not just percentages, so questions about shot
        # volume can be answered from find_games rows without a get_game per game.
        "fg2_made": game.fg2_made,
        "fg2_attempted": game.fg2_attempted,
        "three_made": game.three_made,
        "three_attempted": game.three_attempted,
        "ft_made": game.ft_made,
        "ft_attempted": game.ft_attempted,
        "fg_pct": round(d["fg_pct"] * 100, 1),
        "three_pct": round(d["three_pct"] * 100, 1),
        "ft_pct": round(d["ft_pct"] * 100, 1),
        "ts_pct": round(d["ts_pct"] * 100, 1),
    }


def _sort_value(game: Game, field: str) -> Any:
    if field == "date":
        return game.date
    if field in _PCT_FIELDS:
        return derived_stats(game)[field]  # type: ignore[literal-required]
    return getattr(game, field)


# --------------------------------------------------------------------------- #
# Queries (always scoped to the player)
# --------------------------------------------------------------------------- #


def _team_seasons(db: Session, player: Player) -> list[Season]:
    return list(
        db.scalars(
            select(Season)
            .where(Season.team_id == player.team_id)
            .order_by(Season.start_date.desc())
        ).all()
    )


def _resolve_season(db: Session, player: Player, season_id: UUID | None) -> Season:
    if season_id is None:
        season = db.scalar(
            select(Season).where(
                Season.team_id == player.team_id, Season.end_date.is_(None)
            )
        )
        if season is None:
            raise ToolInputError("There is no active season. Use list_seasons to pick one.")
        return season
    season = db.scalar(
        select(Season).where(Season.id == season_id, Season.team_id == player.team_id)
    )
    if season is None:
        raise ToolInputError(f"Season {season_id} not found. Use list_seasons for valid ids.")
    return season


def _player_games(
    db: Session,
    player: Player,
    season_id: UUID | Literal["all"] | None,
) -> tuple[list[Game], Season | None]:
    stmt = select(Game).where(Game.player_id == player.id)
    season: Season | None = None
    if season_id != "all":
        season = _resolve_season(db, player, season_id)
        stmt = stmt.where(Game.season_id == season.id)
    games = list(db.scalars(stmt.order_by(Game.date.desc())).all())
    return games, season


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #


def list_seasons(db: Session, player: Player, _: ListSeasonsInput) -> dict[str, Any]:
    seasons = _team_seasons(db, player)
    counts: dict[UUID, int] = defaultdict(int)
    for season_id in db.scalars(select(Game.season_id).where(Game.player_id == player.id)):
        counts[season_id] += 1
    return {
        "seasons": [
            {
                "season_id": str(s.id),
                "label": s.label,
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "is_active": s.end_date is None,
                "games_played": counts[s.id],
            }
            for s in seasons
        ]
    }


def get_season_summary(db: Session, player: Player, args: SeasonSummaryInput) -> dict[str, Any]:
    games, season = _player_games(db, player, args.season_id)
    assert season is not None
    totals = {f: sum(getattr(g, f) for g in games) for f in RAW_STAT_FIELDS}
    return {
        "season": season.label,
        "season_id": str(season.id),
        "games_played": len(games),
        "averages": _averages(games, season.id) if games else None,
        "totals": totals if games else None,
        "record": {
            "wins": sum(1 for g in games if g.result == Result.WIN),
            "losses": sum(1 for g in games if g.result == Result.LOSS),
        },
    }


def find_games(db: Session, player: Player, args: FindGamesInput) -> dict[str, Any]:
    games, _ = _player_games(db, player, args.season_id)
    needle = args.opponent.casefold() if args.opponent else None
    matched = [
        g
        for g in games
        if (needle is None or needle in g.opponent.casefold())
        and (args.date_from is None or g.date >= args.date_from)
        and (args.date_to is None or g.date <= args.date_to)
        and (args.result is None or g.result.value == args.result)
        and (args.home_away is None or g.home_away.value == args.home_away)
    ]
    matched.sort(key=lambda g: _sort_value(g, args.sort_by), reverse=args.order == "desc")
    page = matched[: args.limit]
    return {
        "games": [_game_row(g) for g in page],
        "total_matched": len(matched),
        "truncated": len(matched) > len(page),
    }


def get_game(db: Session, player: Player, args: GetGameInput) -> dict[str, Any]:
    stmt = select(Game).where(Game.player_id == player.id)
    if args.game_id is not None:
        stmt = stmt.where(Game.id == args.game_id)
    else:
        stmt = stmt.where(Game.date == args.date)
    matches = list(db.scalars(stmt).all())
    if not matches:
        raise ToolInputError("No game found for this player. Use find_games to look it up.")
    if len(matches) > 1:
        raise ToolInputError(
            "More than one game on that date; call again with one of these game_ids: "
            + ", ".join(str(g.id) for g in matches)
        )
    game = matches[0]
    season = db.get(Season, game.season_id)
    season_games = list(
        db.scalars(
            select(Game).where(Game.player_id == player.id, Game.season_id == game.season_id)
        ).all()
    )
    note = db.scalar(select(CoachNote).where(CoachNote.game_id == game.id))
    return {
        **_game_row(game),
        "season": season.label if season else None,
        "season_highs_set": personal_bests(game, season_games),
        "coach_note": {"author": note.author_name, "text": note.text} if note else None,
    }


def get_split_averages(
    db: Session, player: Player, args: SplitAveragesInput
) -> dict[str, Any]:
    games, _ = _player_games(db, player, args.season_id)
    if args.last_n_games is not None:
        games = games[: args.last_n_games]

    def key(g: Game) -> str:
        match args.group_by:
            case "home_away":
                return "home" if g.home_away == HomeAway.HOME else "away"
            case "result":
                return "wins" if g.result == Result.WIN else "losses"
            case "opponent":
                return g.opponent
            case "month":
                return g.date.strftime("%Y-%m")

    groups: dict[str, list[Game]] = defaultdict(list)
    for g in games:
        groups[key(g)].append(g)
    return {
        "group_by": args.group_by,
        "games_considered": len(games),
        "overall": _averages(games) if games else None,
        "groups": [
            {"group": name, "games": len(gs), "averages": _averages(gs)}
            for name, gs in sorted(groups.items())
        ],
    }


# --------------------------------------------------------------------------- #
# Registry + executor
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    input_model: type[_Input]
    run: Callable[[Session, Player, Any], dict[str, Any]]
    status: str


_TOOLS: tuple[_Tool, ...] = (
    _Tool(
        "list_seasons",
        "List the player's seasons (newest first) with ids, dates and games played. "
        "Use it to resolve a season name like \"last season\" to a season_id.",
        ListSeasonsInput,
        list_seasons,
        "Checking your seasons…",
    ),
    _Tool(
        "get_season_summary",
        "Per-game averages, totals and win/loss record for one season (default: active).",
        SeasonSummaryInput,
        get_season_summary,
        "Pulling your season numbers…",
    ),
    _Tool(
        "find_games",
        "Search the player's games with filters, sorted by date or any stat. Returns full "
        "box-score rows including shot makes and attempts (percentages are 0-100) plus "
        "total_matched/truncated. Use for "
        "\"best game\", \"games vs X\", \"last 3 losses\", streaks and date ranges.",
        FindGamesInput,
        find_games,
        "Looking up your games…",
    ),
    _Tool(
        "get_game",
        "One game's box score plus what find_games doesn't have: season highs set that game "
        "and the coach's note. Pass game_id (from find_games) or the date.",
        GetGameInput,
        get_game,
        "Opening the box score…",
    ),
    _Tool(
        "get_split_averages",
        "Compare the player's per-game averages across groups: home vs away, wins vs losses, "
        "per opponent or per month. Optionally restrict to the last N games.",
        SplitAveragesInput,
        get_split_averages,
        "Crunching your splits…",
    ),
)
_BY_NAME = {t.name: t for t in _TOOLS}


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def tool_definitions() -> list[dict[str, Any]]:
    """Anthropic tool definitions, in a fixed order so the prompt prefix caches."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": _strip_titles(t.input_model.model_json_schema()),
        }
        for t in _TOOLS
    ]


def status_for(names: list[str]) -> str:
    if len(names) == 1 and names[0] in _BY_NAME:
        return _BY_NAME[names[0]].status
    return "Looking things up…"


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool


def execute_tool(name: str, raw_input: Any, db: Session, player: Player) -> ToolOutcome:
    """Run one tool call. Recoverable problems come back as is_error results.

    Database exceptions are left to propagate: the caller decides whether they
    are retryable (Aurora resuming) or a real failure.
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return ToolOutcome(json.dumps({"error": f"Unknown tool {name!r}"}), True)
    try:
        args = tool.input_model.model_validate(raw_input or {})
    except ValidationError as exc:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
            for e in exc.errors()
        ]
        return ToolOutcome(json.dumps({"error": "Invalid arguments", "details": errors}), True)
    try:
        result = tool.run(db, player, args)
    except ToolInputError as exc:
        return ToolOutcome(json.dumps({"error": str(exc)}), True)
    return ToolOutcome(json.dumps(result, ensure_ascii=False, default=str), False)
