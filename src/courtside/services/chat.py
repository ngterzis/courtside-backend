from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Archetype, Game, Player, Season
from courtside.services.stats import personal_bests, season_averages


@dataclass
class ChatContext:
    player: Player
    season: Season | None
    averages: dict[str, Any] | None
    games_played: int
    archetype: Archetype | None
    recent_games: list[Game]
    last_game_bests: list[str]


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
            recent_games=[],
            last_game_bests=[],
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
    last_game_bests = personal_bests(games[0], games) if games else []

    return ChatContext(
        player=player,
        season=season,
        averages=averages,
        games_played=len(games),
        archetype=archetype,
        recent_games=games[:5],
        last_game_bests=last_game_bests,
    )


def build_system_prompt(ctx: ChatContext) -> str:
    lines: list[str] = [
        "You are Courtside Agent, a basketball analytics assistant for a recreational league.",
        "Answer questions about the player's own stats only. Never name or compare teammates.",
        "Do not speculate about playing time, injuries, or coaching decisions.",
        "Be concise and specific — reference actual numbers.",
        "",
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

    if ctx.recent_games:
        lines.append("")
        lines.append("Recent games (last 5, newest first):")
        for g in ctx.recent_games:
            lines.append(
                f"  {g.date.isoformat()} vs {g.opponent} ({g.home_away.value}): "
                f"{g.points}pts {g.rebounds}reb {g.assists}ast"
            )

    if ctx.last_game_bests:
        lines.append("")
        lines.append(f"Last game highlights: {', '.join(ctx.last_game_bests)}")

    return "\n".join(lines)
