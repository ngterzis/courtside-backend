from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.anthropic_client import generate_archetype_explanation
from courtside.auth.deps import get_current_player
from courtside.db.models import Archetype, Game, Player, Season
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.archetype import (
    ArchetypeName,
    ArchetypeOut,
    ArchetypeReceiptLine,
    ArchetypeScore,
)
from courtside.services.archetype import compute_archetype

router = CamelRouter(tags=["archetype"])

MIN_GAMES_FOR_ARCHETYPE = 3


def _current_season_id(db: Session, team_id: UUID) -> UUID:
    season_id = db.scalar(
        select(Season.id).where(
            Season.team_id == team_id, Season.end_date.is_(None)
        )
    )
    if season_id is None:
        raise APIError(404, "no_active_season", "No active season for this team")
    return season_id


def _to_archetype_out(row: Archetype) -> ArchetypeOut:
    return ArchetypeOut(
        primary=ArchetypeName(row.primary_name),
        secondary=ArchetypeName(row.secondary_name),
        explanation=row.explanation,
        receipt=[ArchetypeReceiptLine.model_validate(r) for r in row.receipt],
        scores=(
            [ArchetypeScore.model_validate(s) for s in row.scores]
            if row.scores
            else None
        ),
        assigned_at=row.assigned_at,
        season_id=row.season_id,
    )


@router.get("/api/me/archetype", response_model=ArchetypeOut)
def get_archetype(
    season_id: UUID | None = Query(None, alias="seasonId"),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> ArchetypeOut:
    if season_id is None:
        season_id = _current_season_id(db, player.team_id)

    games_played = len(
        list(
            db.scalars(
                select(Game).where(
                    Game.player_id == player.id, Game.season_id == season_id
                )
            ).all()
        )
    )
    if games_played < MIN_GAMES_FOR_ARCHETYPE:
        raise APIError(
            404,
            "insufficient_games",
            f"Need at least {MIN_GAMES_FOR_ARCHETYPE} games to determine archetype",
        )

    cached = db.scalar(
        select(Archetype).where(
            Archetype.player_id == player.id, Archetype.season_id == season_id
        )
    )
    if cached is not None:
        return _to_archetype_out(cached)

    result = compute_archetype(
        db, team_id=player.team_id, season_id=season_id, player_id=player.id
    )

    receipt_payload = [
        ArchetypeReceiptLine(
            stat=r.stat, value=r.value, percentile=r.percentile, comment=r.comment
        ).model_dump(by_alias=True)
        for r in result.receipt
    ]
    scores_payload = [
        ArchetypeScore(
            name=s.name,
            score=s.score,
            is_primary=True if s.is_primary else None,
            is_secondary=True if s.is_secondary else None,
        ).model_dump(by_alias=True, exclude_none=True)
        for s in result.scores
    ]

    explanation = generate_archetype_explanation(
        result.primary, result.secondary, receipt_payload
    )

    row = Archetype(
        team_id=player.team_id,
        player_id=player.id,
        season_id=season_id,
        primary_name=result.primary,
        secondary_name=result.secondary,
        explanation=explanation,
        receipt=receipt_payload,
        scores=scores_payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_archetype_out(row)


@router.get("/api/me/archetype/history", response_model=list[ArchetypeOut])
def archetype_history(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> list[ArchetypeOut]:
    rows = list(
        db.scalars(
            select(Archetype)
            .where(Archetype.player_id == player.id)
            .order_by(Archetype.assigned_at.desc())
        ).all()
    )
    return [_to_archetype_out(r) for r in rows]
