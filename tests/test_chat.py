import json
from collections.abc import AsyncIterator
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from courtside.db.models import Archetype, Game, Player, Season, User
from courtside.services.chat import build_chat_context, build_system_prompt


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _fake_deltas() -> AsyncIterator[str]:
    for chunk in ["Hello", " there", "!"]:
        yield chunk


def test_chat_streams_sse_format(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
) -> None:
    with patch(
        "courtside.routes.chat.stream_chat_response",
        return_value=_fake_deltas(),
    ):
        r = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "How am I doing?"}]},
            headers=_login(client),
        )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert f"data: {json.dumps({'text': 'Hello'}, separators=(',', ':'))}\n\n" in body
    assert f"data: {json.dumps({'text': ' there'}, separators=(',', ':'))}\n\n" in body
    assert "data: [DONE]\n\n" in body
    assert body.endswith("data: [DONE]\n\n")


def test_chat_passes_player_context_to_anthropic(
    client: TestClient,
    user: User,
    current_season: Season,
    main_games: list[Game],
    player: Player,
) -> None:
    captured: dict[str, object] = {}

    def capture(system_prompt: str, messages: list[dict[str, str]]):
        captured["system"] = system_prompt
        captured["messages"] = messages
        return _fake_deltas()

    with patch("courtside.routes.chat.stream_chat_response", side_effect=capture):
        r = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Talk about my stats"}]},
            headers=_login(client),
        )
    assert r.status_code == 200
    system = captured["system"]
    assert isinstance(system, str)
    assert player.name in system
    assert current_season.label in system
    assert "Season averages:" in system
    assert captured["messages"] == [
        {"role": "user", "content": "Talk about my stats"}
    ]


def test_chat_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 401


def test_chat_validates_request(
    client: TestClient, user: User, current_season: Season, main_games: list[Game]
) -> None:
    r = client.post("/api/chat", json={"messages": []}, headers=_login(client))
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_system_prompt_without_season_or_games(
    db: Session, player: Player
) -> None:
    ctx = build_chat_context(db, player)
    prompt = build_system_prompt(ctx)
    assert player.name in prompt
    assert "no active season" in prompt
    assert "Season averages" not in prompt


def test_system_prompt_omits_teammate_names(
    db: Session,
    player: Player,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    ctx = build_chat_context(db, player)
    prompt = build_system_prompt(ctx)
    for tm in teammates:
        assert tm.name not in prompt


def test_system_prompt_includes_cached_archetype(
    db: Session,
    team,
    player: Player,
    current_season: Season,
    main_games: list[Game],
) -> None:
    db.add(
        Archetype(
            team_id=team.id,
            player_id=player.id,
            season_id=current_season.id,
            primary_name="Playmaker",
            secondary_name="Floor General",
            explanation="Tight handle, elite vision.",
            receipt=[],
            scores=[],
        )
    )
    db.flush()

    ctx = build_chat_context(db, player)
    prompt = build_system_prompt(ctx)
    assert "Playmaker / Floor General" in prompt
    assert "Tight handle, elite vision." in prompt
