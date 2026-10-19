from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from courtside.auth.deps import get_current_player
from courtside.db.models import CoachNote, GamePerformance, Player, Season
from courtside.db.session import get_db
from courtside.errors import APIError
from courtside.routes import CamelRouter
from courtside.schemas.game import (
    CoachNoteOut,
    GameOut,
    GameStatsOut,
    PaginatedGames,
)
from courtside.services.games import player_performances
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
    perf: GamePerformance,
    season_perfs: list[GamePerformance],
    coach_note: CoachNote | None,
) -> GameOut:
    # The API's game id is the performance id: one player's view of one game.
    game = perf.game
    stats = GameStatsOut(
        **{f: getattr(perf, f) for f in RAW_STAT_FIELDS},
        **derived_stats(perf),
    )
    return GameOut(
        id=perf.id,
        season_id=game.season_id,
        date=game.date,
        opponent=game.opponent,
        home_away=game.home_away,
        result=game.result,
        team_score=game.team_score,
        opponent_score=game.opponent_score,
        stats=stats,
        personal_bests=personal_bests(perf, season_perfs),
        coach_note=(
            CoachNoteOut(
                id=coach_note.id,
                game_id=coach_note.performance_id,
                author_name=coach_note.author_name,
                text=coach_note.text,
                created_at=coach_note.created_at,
            )
            if coach_note
            else None
        ),
    )


def _load_coach_notes(
    db: Session, performance_ids: list[UUID]
) -> dict[UUID, CoachNote]:
    if not performance_ids:
        return {}
    notes = db.scalars(
        select(CoachNote).where(CoachNote.performance_id.in_(performance_ids))
    ).all()
    return {n.performance_id: n for n in notes}


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

    season_games = player_performances(db, player.id, season_id)
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
    season_games = player_performances(db, player.id, season_id)
    if not season_games:
        return None
    last = season_games[0]
    note = db.scalar(select(CoachNote).where(CoachNote.performance_id == last.id))
    return _serialize_game(last, season_games, note)


@router.get("/api/games/{game_id}", response_model=GameOut)
def get_game(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> GameOut:
    perf = db.get(GamePerformance, game_id)
    if perf is None or perf.player_id != player.id:
        raise APIError(404, "not_found", "Game not found")
    season_games = player_performances(db, player.id, perf.game.season_id)
    note = db.scalar(select(CoachNote).where(CoachNote.performance_id == game_id))
    return _serialize_game(perf, season_games, note)
