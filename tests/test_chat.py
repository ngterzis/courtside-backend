import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from anthropic.types import Message
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from courtside import anthropic_client
from courtside.anthropic_client import MAX_TOOL_ROUNDS
from courtside.auth.tokens import create_feedback_token, decode_access_token
from courtside.config import get_settings
from courtside.db.models import Archetype, Game, Player, Season, User
from courtside.services.chat import (
    STATIC_INSTRUCTIONS,
    build_chat_context,
    build_player_card,
    build_system_prompt,
)

# --------------------------------------------------------------------------- #
# Fake Anthropic client: replays scripted messages, records every request.
# --------------------------------------------------------------------------- #


def _message(*blocks: dict[str, Any], stop_reason: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": list(blocks),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
    )


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_use(name: str, tool_input: dict[str, Any], tid: str = "tu_1") -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": name, "input": tool_input}


class _FakeStream:
    def __init__(self, message: Message) -> None:
        self._message = message

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    async def text_stream(self) -> AsyncIterator[str]:  # type: ignore[override]
        for block in self._message.content:
            if block.type == "text":
                for word in block.text.split(" "):
                    yield word + " "

    async def get_final_message(self) -> Message:
        return self._message


class FakeAnthropic:
    def __init__(self, script: list[Message]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []
        outer = self

        class _Messages:
            def stream(self, **kwargs: Any) -> _FakeStream:
                # Snapshot: the loop appends to the same list between rounds.
                outer.requests.append({**kwargs, "messages": list(kwargs["messages"])})
                return _FakeStream(outer.script.pop(0))

        self.messages = _Messages()


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")

    @contextmanager
    def install(*script: Message) -> Iterator[FakeAnthropic]:
        fake = FakeAnthropic(list(script))
        with patch.object(anthropic_client.anthropic, "AsyncAnthropic", return_value=fake):
            yield fake

    yield install


def _login(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"email": "player@example.com", "password": "secret"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _events(body: str) -> list[Any]:
    out: list[Any] = []
    for chunk in body.split("\n\n"):
        if not chunk:
            continue
        assert chunk.startswith("data: ")
        data = chunk.removeprefix("data: ")
        out.append(data if data == "[DONE]" else json.loads(data))
    return out


def _chat(client: TestClient, text: str = "How am I doing?") -> list[Any]:
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": text}]},
        headers=_login(client),
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    return _events(r.text)


# --------------------------------------------------------------------------- #
# Streaming + tool loop
# --------------------------------------------------------------------------- #


def test_chat_streams_plain_answer(
    client: TestClient, user: User, current_season: Season, main_games: list[Game], fake_llm
) -> None:
    with fake_llm(_message(_text("Hello there!"))) as fake:
        events = _chat(client)

    assert events[-1] == "[DONE]"
    assert "".join(e["text"] for e in events[:-1]) == "Hello there! "
    req = fake.requests[0]
    assert [t["name"] for t in req["tools"]][0] == "list_seasons"
    assert req["messages"] == [{"role": "user", "content": "How am I doing?"}]
    assert "tool_choice" not in req


def test_chat_runs_tools_and_returns_results_to_the_model(
    client: TestClient,
    user: User,
    player: Player,
    current_season: Season,
    main_games: list[Game],
    fake_llm,
) -> None:
    best = max(main_games, key=lambda g: g.points)
    script = (
        _message(
            _text("Let me check."),
            _tool_use("find_games", {"sort_by": "points", "limit": 1}, "tu_a"),
            _tool_use("get_split_averages", {"group_by": "result"}, "tu_b"),
            stop_reason="tool_use",
        ),
        _message(_text(f"Your best was {best.points} points.")),
    )
    with fake_llm(*script) as fake:
        events = _chat(client, "Best game?")

    statuses = [e["status"] for e in events if isinstance(e, dict) and "status" in e]
    assert statuses == ["Looking things up…"]
    text = "".join(e["text"] for e in events if isinstance(e, dict) and "text" in e)
    assert text == f"Let me check. \n\nYour best was {best.points} points. "

    # Both results go back in ONE user message, matched to their tool_use ids.
    followup = fake.requests[1]["messages"]
    assert followup[1]["role"] == "assistant"
    results = followup[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_a", "tu_b"]
    assert all(r["is_error"] is False for r in results)
    games = json.loads(results[0]["content"])["games"]
    assert games[0]["game_id"] == str(best.id)


def test_chat_returns_tool_errors_to_the_model(
    client: TestClient, user: User, current_season: Season, fake_llm
) -> None:
    script = (
        _message(_tool_use("get_game", {"game_id": "nope"}), stop_reason="tool_use"),
        _message(_text("I couldn't find that game.")),
    )
    with fake_llm(*script) as fake:
        events = _chat(client)

    result = fake.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True
    assert "Invalid arguments" in result["content"]
    assert events[-1] == "[DONE]"


def test_chat_caps_tool_rounds(
    client: TestClient, user: User, current_season: Season, fake_llm
) -> None:
    loop = [
        _message(_tool_use("list_seasons", {}, f"tu_{i}"), stop_reason="tool_use")
        for i in range(MAX_TOOL_ROUNDS)
    ]
    with fake_llm(*loop, _message(_text("Here is what I found."))) as fake:
        events = _chat(client)

    assert len(fake.requests) == MAX_TOOL_ROUNDS + 1
    assert fake.requests[-1]["tool_choice"] == {"type": "none"}
    assert events[-2]["text"].strip() == "found."
    assert events[-1] == "[DONE]"


def test_chat_stream_ends_cleanly_on_upstream_error(
    client: TestClient, user: User, current_season: Season, fake_llm
) -> None:
    with fake_llm() as fake:  # empty script: the first stream() call raises
        fake.script = []
        events = _chat(client)
    assert "something went wrong" in events[-2]["text"]
    assert events[-1] == "[DONE]"


def test_chat_without_api_key_uses_fallback(
    client: TestClient, user: User, current_season: Season, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    events = _chat(client)
    assert "Chat is not configured" in "".join(e["text"] for e in events[:-1])
    # Tracing is off by default, so no feedback token is sent.
    assert not any(isinstance(e, dict) and "feedback" in e for e in events)


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


# --------------------------------------------------------------------------- #
# Tracing + feedback
# --------------------------------------------------------------------------- #


class _FakeSpan:
    def __init__(self, log: list[dict[str, Any]], **kwargs: Any) -> None:
        self.log = log
        self.record = {**kwargs, "updates": [], "ended": False}
        log.append(self.record)

    def start_observation(self, **kwargs: Any) -> "_FakeSpan":
        return _FakeSpan(self.log, **kwargs)

    def update(self, **kwargs: Any) -> None:
        self.record["updates"].append(kwargs)

    def end(self) -> None:
        self.record["ended"] = True


class FakeLangfuse:
    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []
        self.flushes = 0

    def create_trace_id(self) -> str:
        return "a" * 32

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[_FakeSpan]:
        yield _FakeSpan(self.spans, **kwargs)

    def create_score(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushes += 1


@pytest.fixture
def fake_langfuse() -> Iterator[FakeLangfuse]:
    fake = FakeLangfuse()
    with patch("courtside.observability.get_langfuse", return_value=fake):
        yield fake


def test_chat_trace_tree_and_feedback_token(
    client: TestClient,
    user: User,
    player: Player,
    current_season: Season,
    main_games: list[Game],
    fake_llm,
    fake_langfuse: FakeLangfuse,
) -> None:
    script = (
        _message(_tool_use("find_games", {}), stop_reason="tool_use"),
        _message(_text("Done.")),
    )
    with fake_llm(*script):
        events = _chat(client)

    token = events[0]["feedback"]
    # A feedback token must never work as an access token.
    with pytest.raises(Exception):  # noqa: B017
        decode_access_token(token)

    names = [(s["name"], s.get("as_type")) for s in fake_langfuse.spans]
    assert names == [
        ("chat.turn", "agent"),
        ("llm.round.1", "generation"),
        ("find_games", "tool"),
        ("llm.round.2", "generation"),
    ]
    gen = fake_langfuse.spans[1]
    usage = next(u["usage_details"] for u in gen["updates"] if "usage_details" in u)
    assert usage["input"] == 100 and gen["ended"]
    root_meta = fake_langfuse.spans[0]["updates"][-1]["metadata"]
    assert root_meta["rounds"] == 2 and root_meta["tool_calls"] == ["find_games"]
    assert fake_langfuse.flushes == 1

    r = client.post(
        "/api/chat/feedback",
        json={"token": token, "score": -1, "comment": "wrong number"},
        headers=_login(client),
    )
    assert r.status_code == 200
    assert fake_langfuse.scores == [
        {
            "name": "user_feedback",
            "value": -1,
            "trace_id": "a" * 32,
            "data_type": "NUMERIC",
            "comment": "wrong number",
        }
    ]


def test_feedback_rejects_other_players_and_bad_tokens(
    client: TestClient,
    user: User,
    teammates: list[Player],
    fake_langfuse: FakeLangfuse,
) -> None:
    headers = _login(client)
    other = create_feedback_token("b" * 32, teammates[0].id)
    r = client.post("/api/chat/feedback", json={"token": other, "score": 1}, headers=headers)
    assert r.status_code == 403

    r = client.post("/api/chat/feedback", json={"token": "junk", "score": 1}, headers=headers)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_feedback_token"

    r = client.post(
        "/api/chat/feedback", json={"token": "junk", "score": 5}, headers=headers
    )
    assert r.status_code == 422
    assert fake_langfuse.scores == []


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #


def test_system_prompt_is_cached_static_block_plus_card(
    db: Session, player: Player, current_season: Season, main_games: list[Game]
) -> None:
    blocks = build_system_prompt(build_chat_context(db, player), today=date(2026, 4, 1))
    assert blocks[0]["text"] == STATIC_INSTRUCTIONS
    assert blocks[0].get("cache_control") == {"type": "ephemeral"}
    card = blocks[1]["text"]
    assert "cache_control" not in blocks[1]
    assert "Today: 2026-04-01" in card
    assert player.name in card
    assert current_season.label in card
    assert "Season averages:" in card
    # Per-game detail now comes from tools, not the prompt.
    assert "Recent games" not in card


def test_system_prompt_without_season_or_games(db: Session, player: Player) -> None:
    card = build_player_card(build_chat_context(db, player))
    assert player.name in card
    assert "no active season" in card
    assert "Season averages" not in card


def test_system_prompt_omits_teammate_names(
    db: Session,
    player: Player,
    current_season: Season,
    main_games: list[Game],
    teammates: list[Player],
    teammate_games: list[Game],
) -> None:
    blocks = build_system_prompt(build_chat_context(db, player))
    prompt = "\n".join(b["text"] for b in blocks)
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

    card = build_player_card(build_chat_context(db, player))
    assert "Playmaker / Floor General" in card
    assert "Tight handle, elite vision." in card
