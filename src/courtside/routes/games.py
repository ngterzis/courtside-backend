from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import CoachNote, Game, Player, Season
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.game import (
    CoachNoteOut,
    GameOut,
    GameStatsOut,
    PaginatedGames,
)
from courtside.services.stats import (
    RAW_STAT_FIELDS,
    derived_stats,
    personal_bests,
)

router = CamelRouter(tags=["games"])


def _current_season_id(db: Session, team_id: UUID) -> UUID:
    season_id = db.scalar(
        select(Season.id).where(
            Season.team_id == team_id, Season.end_date.is_(None)
        )
    )
    if season_id is None:
        raise APIError(404, "no_active_season", "No active season for this team")
    return season_id


def _serialize_game(
    game: Game, season_games: list[Game], coach_note: CoachNote | None
) -> GameOut:
    stats = GameStatsOut(
        **{f: getattr(game, f) for f in RAW_STAT_FIELDS},
        **derived_stats(game),
    )
    return GameOut(
        id=game.id,
        season_id=game.season_id,
        date=game.date,
        opponent=game.opponent,
        home_away=game.home_away,
        result=game.result,
        team_score=game.team_score,
        opponent_score=game.opponent_score,
        stats=stats,
        personal_bests=personal_bests(game, season_games),
        coach_note=CoachNoteOut.model_validate(coach_note) if coach_note else None,
    )


def _load_season_games(db: Session, player_id: UUID, season_id: UUID) -> list[Game]:
    return list(
        db.scalars(
            select(Game)
            .where(Game.player_id == player_id, Game.season_id == season_id)
            .order_by(Game.date.desc())
        ).all()
    )


def _load_coach_notes(
    db: Session, game_ids: list[UUID]
) -> dict[UUID, CoachNote]:
    if not game_ids:
        return {}
    notes = db.scalars(
        select(CoachNote).where(CoachNote.game_id.in_(game_ids))
    ).all()
    return {n.game_id: n for n in notes}


@router.get("/api/me/games", response_model=PaginatedGames)
def list_my_games(
    season_id: UUID | None = Query(None, alias="seasonId"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> PaginatedGames:
    if season_id is None:
        season_id = _current_season_id(db, player.team_id)

    season_games = _load_season_games(db, player.id, season_id)
    page = season_games[offset : offset + limit]
    notes = _load_coach_notes(db, [g.id for g in page])
    return PaginatedGames(
        games=[_serialize_game(g, season_games, notes.get(g.id)) for g in page],
        total=len(season_games),
    )


@router.get("/api/me/games/last", response_model=GameOut | None)
def last_game(
    season_id: UUID | None = Query(None, alias="seasonId"),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> GameOut | None:
    if season_id is None:
        season_id = _current_season_id(db, player.team_id)
    season_games = _load_season_games(db, player.id, season_id)
    if not season_games:
        return None
    last = season_games[0]
    note = db.scalar(select(CoachNote).where(CoachNote.game_id == last.id))
    return _serialize_game(last, season_games, note)


@router.get("/api/games/{game_id}", response_model=GameOut)
def get_game(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> GameOut:
    game = db.get(Game, game_id)
    if game is None or game.player_id != player.id:
        raise APIError(404, "not_found", "Game not found")
    season_games = _load_season_games(db, player.id, game.season_id)
    note = db.scalar(select(CoachNote).where(CoachNote.game_id == game_id))
    return _serialize_game(game, season_games, note)
