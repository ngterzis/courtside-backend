from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from anthropic.types import TextBlockParam
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Archetype, Game, Player, Season
from courtside.services.stats import season_averages


@dataclass
class ChatContext:
    player: Player
    season: Season | None
    averages: dict[str, Any] | None
    games_played: int
    archetype: Archetype | None


def build_chat_context(db: Session, player: Player) -> ChatContext:
    season = db.scalar(
        select(Season).where(
            Season.team_id == player.team_id, Season.end_date.is_(None)
        )
    )
    if season is None:
        return ChatContext(
            player=player,
            season=None,
            averages=None,
            games_played=0,
            archetype=None,
        )

    games = list(
        db.scalars(
            select(Game)
            .where(Game.player_id == player.id, Game.season_id == season.id)
            .order_by(Game.date.desc())
        ).all()
    )
    averages = season_averages(games, season.id) if games else None
    archetype = db.scalar(
        select(Archetype).where(
            Archetype.player_id == player.id, Archetype.season_id == season.id
        )
    )

    return ChatContext(
        player=player,
        season=season,
        averages=averages,
        games_played=len(games),
        archetype=archetype,
    )


PROMPT_VERSION = "2026-10-19.tools-v4"

# Static instructions: identical for every player and request so that, together
# with the tool definitions ahead of it, it forms a cacheable prompt prefix.
# Anything per-player or per-day belongs in the player card instead.
STATIC_INSTRUCTIONS = """\
You are Courtside Agent, a basketball analytics assistant for a recreational league.
Answer questions about the player's own stats only. Never name or compare teammates.
Do not speculate about playing time, injuries, or coaching decisions.
Be concise and specific — reference actual numbers.

The player card below holds the active season's averages and archetype. For anything \
about individual games, opponents, dates, splits (home/away, wins/losses, months), \
streaks or past seasons, use the tools — they only ever return this player's data. \
Never estimate or invent a number; if the data isn't there, say so plainly. \
Percentages in tool results are on a 0-100 scale.

The player never sees your tools, so talk about their game, not your process. \
The app already shows a status line while you look things up, so call tools without \
announcing them, and start your reply with the answer itself. Never mention tools, \
tool calls, searches, ids, the player card, or data you already fetched; when you \
reuse earlier results, just state the numbers."""


def build_player_card(ctx: ChatContext, today: date | None = None) -> str:
    today = today or date.today()
    lines: list[str] = [
        f"Today: {today.isoformat()}",
        (
            f"Player: {ctx.player.name}, #{ctx.player.jersey_number}, "
            f"{ctx.player.position.value}"
        ),
    ]

    if ctx.season is not None:
        lines.append(f"Season: {ctx.season.label} ({ctx.games_played} games)")
    else:
        lines.append("Season: no active season")

    if ctx.averages is not None:
        a = ctx.averages
        lines.extend(
            [
                "",
                "Season averages:",
                (
                    f"  PTS {a['points']:.1f} | AST {a['assists']:.1f} | "
                    f"REB {a['rebounds']:.1f} | STL {a['steals']:.1f}"
                ),
                (
                    f"  TOV {a['turnovers']:.1f} | TS% {a['ts_pct'] * 100:.1f} | "
                    f"FG% {a['fg_pct'] * 100:.1f} | 3PT% {a['three_pct'] * 100:.1f}"
                ),
            ]
        )

    if ctx.archetype is not None:
        lines.extend(
            [
                "",
                f"Archetype: {ctx.archetype.primary_name} / {ctx.archetype.secondary_name}",
                f'  "{ctx.archetype.explanation}"',
            ]
        )

    return "\n".join(lines)


def build_system_prompt(
    ctx: ChatContext, today: date | None = None
) -> list[TextBlockParam]:
    """System prompt as two blocks: cached static instructions, then the card."""
    return [
        {
            "type": "text",
            "text": STATIC_INSTRUCTIONS,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": build_player_card(ctx, today)},
    ]
