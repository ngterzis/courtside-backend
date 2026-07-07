"""Wipe local data and load real Λάσπη BC stats from laspi_bc_stats.csv.

Usage:
    uv run python scripts/seed.py
"""
from __future__ import annotations

import csv
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete

from courtside.auth.tokens import hash_password
from courtside.db.models import (
    Archetype,
    CoachNote,
    Game,
    HomeAway,
    Notification,
    Player,
    Position,
    Result,
    Season,
    Team,
    User,
)
from courtside.db.session import get_session_factory

CSV_PATH = Path(__file__).parent.parent / "laspi_bc_stats.csv"
TEAM_NAME = "Λάσπη BC"
TEAM_NAME_FRAGMENT = "σπη"  # matches both Λάσπη and Λασπη
SEASON_LABEL = "2025-26"
SEASON_START = date(2025, 9, 1)

# One login per roster player. player_name must match the normalised CSV name
# exactly (see _normalize), otherwise the user won't link to a player — the guard
# in main() will fail the seed if that happens.
SEED_USERS = [
    {"email": "nikos@courtside.dev", "password": "password123", "player_name": "Τερζής, Νικόλαος"},
    {"email": "pavlos@courtside.dev", "password": "password123", "player_name": "Πλυτάς, Παύλος"},
    {"email": "thodoris@courtside.dev", "password": "password123", "player_name": "Σαμαράς, Θοδωρής"},
    {"email": "dimitris.samaras@courtside.dev", "password": "password123", "player_name": "Samaras, Dimitris"},
    {"email": "dimitris.padouvas@courtside.dev", "password": "password123", "player_name": "Παδουβας, Δημητρης"},
    {"email": "nikolas.chatzis@courtside.dev", "password": "password123", "player_name": "Χατζής, Νικόλας"},
    {"email": "michalis.papakonstantinou@courtside.dev", "password": "password123", "player_name": "Παπακωνσταντινου, Μιχάλης"},
    {"email": "dimitris.papakonstantinou@courtside.dev", "password": "password123", "player_name": "Παπακωνσταντίνου, Δημήτρης"},
    {"email": "alexandros.asfis@courtside.dev", "password": "password123", "player_name": "Ασφής, Αλέξανδρος"},
    {"email": "dimitris.papapantelidis@courtside.dev", "password": "password123", "player_name": "Παπαπαντελίδης, Δημήτρης"},
    {"email": "apostolos.kyriakopoulos@courtside.dev", "password": "password123", "player_name": "Kyriakopoulos, Apostolos"},
]


def _normalize(name: str) -> str:
    """Strip stray whitespace around commas and normalise unicode."""
    parts = [part.strip() for part in name.split(",")]
    return unicodedata.normalize("NFC", ", ".join(parts))


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%d/%m/%Y").date()


def _parse_match(match: str, score: str) -> tuple[str, HomeAway, int, int, Result]:
    """Return (opponent, home_away, team_score, opponent_score, result)."""
    home_name, away_name = match.split(" - ", 1)
    laspi_is_home = TEAM_NAME_FRAGMENT in home_name
    opponent = away_name if laspi_is_home else home_name

    home_score, away_score = (int(s.strip()) for s in score.split(" - ", 1))
    if laspi_is_home:
        team_score, opp_score, home_away = home_score, away_score, HomeAway.HOME
    else:
        team_score, opp_score, home_away = away_score, home_score, HomeAway.AWAY

    result = Result.WIN if team_score > opp_score else Result.LOSS
    return opponent, home_away, team_score, opp_score, result


def _wipe(db) -> None:
    for model in (Notification, Archetype, CoachNote, Game, Season, User, Player, Team):
        db.execute(delete(model))


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))

    SessionLocal = get_session_factory()
    with SessionLocal() as db:
        _wipe(db)
        db.commit()

        team = Team(name=TEAM_NAME)
        db.add(team)
        db.flush()

        # Create one Player per unique normalised name
        seeded_norms = {_normalize(u["player_name"]) for u in SEED_USERS}
        player_map: dict[str, Player] = {}
        for row in rows:
            norm = _normalize(row["player"])
            if norm not in player_map:
                player = Player(
                    team_id=team.id,
                    name=norm,
                    jersey_number=0,
                    position=Position.GUARD,
                    onboarded_at=datetime.now(timezone.utc) if norm in seeded_norms else None,
                )
                db.add(player)
                player_map[norm] = player
        db.flush()

        unmatched = [u["email"] for u in SEED_USERS if _normalize(u["player_name"]) not in player_map]
        if unmatched:
            raise SystemExit(
                f"Seed users with no matching player (check player_name spelling): {unmatched}"
            )

        for u in SEED_USERS:
            norm = _normalize(u["player_name"])
            linked_player = player_map.get(norm)
            db.add(
                User(
                    email=u["email"],
                    password_hash=hash_password(u["password"]),
                    player_id=linked_player.id if linked_player else None,
                )
            )

        season = Season(
            team_id=team.id,
            label=SEASON_LABEL,
            start_date=SEASON_START,
            end_date=None,
        )
        db.add(season)
        db.flush()

        for row in rows:
            opponent, home_away, team_score, opp_score, result = _parse_match(
                row["match"], row["score"]
            )
            player = player_map[_normalize(row["player"])]
            db.add(
                Game(
                    team_id=team.id,
                    player_id=player.id,
                    season_id=season.id,
                    date=_parse_date(row["date"]),
                    opponent=opponent,
                    home_away=home_away,
                    result=result,
                    team_score=team_score,
                    opponent_score=opp_score,
                    points=int(row["pts"]),
                    rebounds=int(row["reb_off"]) + int(row["reb_def"]),
                    assists=int(row["ast"]),
                    steals=int(row["stl"]),
                    blocks=int(row["blk"]),
                    turnovers=int(row["to"]),
                    fouls=int(row["fls"]),
                    fg_made=int(row["fg2_made"]),
                    fg_attempted=int(row["fg2_attempted"]),
                    three_made=int(row["fg3_made"]),
                    three_attempted=int(row["fg3_attempted"]),
                    ft_made=int(row["ft_made"]),
                    ft_attempted=int(row["ft_attempted"]),
                )
            )

        db.commit()

    print("Seed complete.")
    print(f"  team:    {TEAM_NAME}")
    print(f"  players: {len(player_map)}")
    print(f"  season:  {SEASON_LABEL}")
    print(f"  games:   {len(rows)} player-game rows across {len({r['match'] + r['date'] for r in rows})} games")
    print()
    print("Logins:")
    for u in SEED_USERS:
        print(f"  {u['email']} / {u['password']}")


if __name__ == "__main__":
    main()
