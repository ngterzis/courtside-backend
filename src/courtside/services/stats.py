from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Game, Player

RAW_STAT_FIELDS: tuple[str, ...] = (
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "fouls",
    "fg_made",
    "fg_attempted",
    "three_made",
    "three_attempted",
    "ft_made",
    "ft_attempted",
)

PERSONAL_BEST_FIELDS: tuple[str, ...] = (
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "fg_made",
    "three_made",
    "ft_made",
)


def _ratio(made: float, attempted: float) -> float:
    return made / attempted if attempted else 0.0


def _ts_pct(points: float, fg_attempted: float, ft_attempted: float) -> float:
    denom = 2 * (fg_attempted + 0.44 * ft_attempted)
    return points / denom if denom else 0.0


def derived_stats(game: Game) -> dict[str, float]:
    return {
        "fg_pct": _ratio(game.fg_made, game.fg_attempted),
        "three_pct": _ratio(game.three_made, game.three_attempted),
        "ft_pct": _ratio(game.ft_made, game.ft_attempted),
        "ts_pct": _ts_pct(game.points, game.fg_attempted, game.ft_attempted),
    }


def personal_bests(game: Game, season_games: Iterable[Game]) -> list[str]:
    games = list(season_games)
    if not games:
        return []
    bests: list[str] = []
    for field in PERSONAL_BEST_FIELDS:
        value = getattr(game, field)
        if value <= 0:
            continue
        season_max = max(getattr(g, field) for g in games)
        if value == season_max:
            bests.append(_snake_to_camel(field))
    return bests


def season_averages(games: list[Game], season_id: UUID) -> dict[str, Any]:
    n = len(games)
    out: dict[str, Any] = {"season_id": season_id, "games_played": n}
    if n == 0:
        for f in RAW_STAT_FIELDS:
            out[f] = 0.0
        out["fg_pct"] = 0.0
        out["three_pct"] = 0.0
        out["ft_pct"] = 0.0
        out["ts_pct"] = 0.0
        return out

    sums = {f: sum(getattr(g, f) for g in games) for f in RAW_STAT_FIELDS}
    for f, total in sums.items():
        out[f] = total / n
    out["fg_pct"] = _ratio(sums["fg_made"], sums["fg_attempted"])
    out["three_pct"] = _ratio(sums["three_made"], sums["three_attempted"])
    out["ft_pct"] = _ratio(sums["ft_made"], sums["ft_attempted"])
    out["ts_pct"] = _ts_pct(
        sums["points"], sums["fg_attempted"], sums["ft_attempted"]
    )
    return out


def team_ranks(
    db: Session,
    *,
    team_id: UUID,
    season_id: UUID,
    player_id: UUID,
    stats: Iterable[str],
) -> list[dict[str, Any]]:
    players = list(db.scalars(select(Player).where(Player.team_id == team_id)).all())
    averages_by_player: dict[UUID, dict[str, Any]] = {}
    for p in players:
        games = list(
            db.scalars(
                select(Game).where(
                    Game.player_id == p.id, Game.season_id == season_id
                )
            ).all()
        )
        if not games:
            continue
        averages_by_player[p.id] = season_averages(games, season_id)

    if player_id not in averages_by_player:
        return []

    out: list[dict[str, Any]] = []
    for stat in stats:
        scored = sorted(
            averages_by_player.items(),
            key=lambda item: item[1][stat],
            reverse=True,
        )
        rank = next(i + 1 for i, (pid, _) in enumerate(scored) if pid == player_id)
        total = len(scored)
        pct = _percentile_for_rank(rank, total)
        out.append(
            {
                "stat": _snake_to_camel(stat),
                "percentile": pct,
                "label": _label_for(pct, rank),
            }
        )
    return out


def _percentile_for_rank(rank: int, total: int) -> float:
    if total <= 1:
        return 100.0
    return (total - rank) / (total - 1) * 100


def _label_for(percentile: float, rank: int) -> str:
    if percentile >= 90:
        return f"#{rank} on team"
    if percentile >= 70:
        return "top 3"
    if percentile >= 50:
        return "above avg"
    if percentile >= 30:
        return "below avg"
    return "bottom 3"


def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])
