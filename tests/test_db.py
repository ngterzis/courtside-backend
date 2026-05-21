from datetime import date

from sqlalchemy.orm import Session

from courtside.db.models import (
    Game,
    HomeAway,
    Notification,
    NotificationType,
    Player,
    Position,
    Result,
    Season,
    Team,
)


def test_can_create_team_and_player(db: Session) -> None:
    team = Team(name="Test Team")
    db.add(team)
    db.flush()

    player = Player(
        team_id=team.id,
        name="Test Player",
        jersey_number=23,
        position=Position.GUARD,
    )
    db.add(player)
    db.flush()

    assert player.id is not None
    assert player.team_id == team.id
    assert player.position == Position.GUARD
    assert player.onboarded_at is None


def test_can_create_game_with_stats(db: Session) -> None:
    team = Team(name="Test Team")
    db.add(team)
    db.flush()
    player = Player(
        team_id=team.id, name="P", jersey_number=1, position=Position.GUARD
    )
    db.add(player)
    season = Season(team_id=team.id, label="Spring '26", start_date=date(2026, 3, 1))
    db.add(season)
    db.flush()

    game = Game(
        team_id=team.id,
        player_id=player.id,
        season_id=season.id,
        date=date(2026, 3, 10),
        opponent="Rivals",
        home_away=HomeAway.HOME,
        result=Result.WIN,
        team_score=88,
        opponent_score=72,
        points=22,
        rebounds=5,
        assists=7,
        steals=2,
        blocks=0,
        turnovers=3,
        fouls=2,
        fg_made=8,
        fg_attempted=15,
        three_made=3,
        three_attempted=7,
        ft_made=3,
        ft_attempted=4,
    )
    db.add(game)
    db.flush()

    assert game.id is not None
    assert game.points == 22


def test_notification_payload_jsonb(db: Session) -> None:
    team = Team(name="Test Team")
    db.add(team)
    db.flush()
    player = Player(
        team_id=team.id, name="P", jersey_number=1, position=Position.FORWARD
    )
    db.add(player)
    db.flush()

    notif = Notification(
        team_id=team.id,
        player_id=player.id,
        type=NotificationType.PERSONAL_BEST,
        payload={"stat": "points", "value": 28},
    )
    db.add(notif)
    db.flush()

    assert notif.id is not None
    assert notif.payload["stat"] == "points"
    assert notif.read_at is None
