from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.db.models import Game, Player
from courtside.services.stats import season_averages

ARCHETYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "Playmaker": {"assists": 0.5, "ts_pct": 0.2, "points": 0.1, "turnovers": 0.2},
    "Efficient Scorer": {"ts_pct": 0.4, "fg_pct": 0.2, "points": 0.3, "turnovers": 0.1},
    "Glass Cleaner": {"rebounds": 0.7, "blocks": 0.2, "fouls": 0.1},
    "Defensive Anchor": {"steals": 0.3, "blocks": 0.3, "rebounds": 0.2, "fouls": 0.2},
    "3&D Wing": {"three_pct": 0.4, "three_made": 0.3, "steals": 0.2, "ts_pct": 0.1},
    "Rim Protector": {"blocks": 0.6, "rebounds": 0.3, "fouls": 0.1},
    "Spark Plug": {"points": 0.4, "steals": 0.3, "fg_pct": 0.2, "ts_pct": 0.1},
    "Floor General": {"assists": 0.4, "ts_pct": 0.2, "steals": 0.2, "turnovers": 0.2},
    "Hustle Player": {"steals": 0.3, "rebounds": 0.3, "blocks": 0.2, "fouls": 0.2},
}

LOWER_IS_BETTER: frozenset[str] = frozenset({"turnovers", "fouls"})

STAT_LABELS: dict[str, str] = {
    "points": "PTS/g",
    "rebounds": "REB/g",
    "assists": "AST/g",
    "steals": "STL/g",
    "blocks": "BLK/g",
    "turnovers": "TOV/g",
    "fouls": "PF/g",
    "ts_pct": "TS%",
    "fg_pct": "FG%",
    "three_pct": "3PT%",
    "ft_pct": "FT%",
    "three_made": "3PT made/g",
}

COMMENT_PHRASES: dict[str, str] = {
    "points": "scoring volume",
    "rebounds": "rebounding",
    "assists": "playmaking",
    "steals": "defensive activity",
    "blocks": "rim protection",
    "turnovers": "ball security",
    "fouls": "discipline",
    "ts_pct": "scoring efficiency",
    "fg_pct": "shooting efficiency",
    "three_pct": "outside shooting",
    "ft_pct": "free-throw shooting",
    "three_made": "perimeter shooting",
}


@dataclass
class ReceiptLine:
    stat: str
    value: str
    percentile: float
    comment: str


@dataclass
class Score:
    name: str
    score: float
    is_primary: bool = False
    is_secondary: bool = False


@dataclass
class ArchetypeResult:
    primary: str
    secondary: str
    receipt: list[ReceiptLine] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)


def compute_archetype(
    db: Session,
    *,
    team_id: UUID,
    season_id: UUID,
    player_id: UUID,
) -> ArchetypeResult:
    averages_by_player = _team_averages(db, team_id, season_id)
    if player_id not in averages_by_player:
        raise ValueError("target player has no games in this season")

    percentiles = _goodness_percentiles(player_id, averages_by_player)

    scores: list[Score] = [
        Score(name=name, score=_score_archetype(percentiles, weights))
        for name, weights in ARCHETYPE_WEIGHTS.items()
    ]
    scores.sort(key=lambda s: s.score, reverse=True)
    scores[0].is_primary = True
    if len(scores) > 1:
        scores[1].is_secondary = True

    receipt = _build_receipt(scores[0].name, averages_by_player[player_id], percentiles)
    secondary = scores[1].name if len(scores) > 1 else scores[0].name
    return ArchetypeResult(
        primary=scores[0].name,
        secondary=secondary,
        receipt=receipt,
        scores=scores,
    )


def _team_averages(
    db: Session, team_id: UUID, season_id: UUID
) -> dict[UUID, dict[str, float]]:
    players = list(db.scalars(select(Player).where(Player.team_id == team_id)).all())
    out: dict[UUID, dict[str, float]] = {}
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
        out[p.id] = season_averages(games, season_id)
    return out


def _goodness_percentiles(
    target_player_id: UUID,
    averages_by_player: dict[UUID, dict[str, float]],
) -> dict[str, float]:
    relevant = {s for weights in ARCHETYPE_WEIGHTS.values() for s in weights}
    result: dict[str, float] = {}
    for stat in relevant:
        scored = sorted(
            averages_by_player.items(),
            key=lambda item: item[1].get(stat, 0.0),
            reverse=stat not in LOWER_IS_BETTER,
        )
        rank = next(
            i + 1 for i, (pid, _) in enumerate(scored) if pid == target_player_id
        )
        result[stat] = _percentile_for_rank(rank, len(scored))
    return result


def _score_archetype(
    percentiles: dict[str, float], weights: dict[str, float]
) -> float:
    total_weight = sum(weights.values())
    if total_weight == 0:
        return 0.0
    weighted = sum(w * percentiles.get(s, 50.0) for s, w in weights.items())
    return weighted / total_weight


def _build_receipt(
    primary: str,
    averages: dict[str, float],
    percentiles: dict[str, float],
) -> list[ReceiptLine]:
    weights = ARCHETYPE_WEIGHTS[primary]
    contributions = sorted(
        ((stat, weights[stat] * percentiles.get(stat, 50.0)) for stat in weights),
        key=lambda x: x[1],
        reverse=True,
    )
    top = contributions[:5]

    lines: list[ReceiptLine] = []
    for stat, _ in top:
        pct = percentiles.get(stat, 50.0)
        lines.append(
            ReceiptLine(
                stat=STAT_LABELS.get(stat, stat),
                value=_format_value(stat, averages.get(stat, 0.0)),
                percentile=pct,
                comment=f"{_bucket_label(pct)} {COMMENT_PHRASES.get(stat, stat)}",
            )
        )
    return lines


def _format_value(stat: str, value: float) -> str:
    if stat.endswith("_pct"):
        return f"{value * 100:.1f}%"
    return f"{value:.1f}"


def _bucket_label(percentile: float) -> str:
    if percentile >= 90:
        return "elite"
    if percentile >= 70:
        return "strong"
    if percentile >= 50:
        return "above-average"
    if percentile >= 30:
        return "below-average"
    return "limited"


def _percentile_for_rank(rank: int, total: int) -> float:
    if total <= 1:
        return 100.0
    return (total - rank) / (total - 1) * 100
