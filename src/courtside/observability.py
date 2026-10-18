"""Tracing for chat turns: Langfuse (OpenTelemetry under the hood) plus a log line.

One chat turn is one trace:

    chat.turn (agent)            input: user message, output: full answer
    ├── llm.round.1 (generation) model, messages, usage incl. cache, stop_reason, TTFT
    ├── find_games (tool)        input args, output JSON, level=ERROR on is_error
    └── llm.round.2 (generation)

Langfuse is optional. Without LANGFUSE_PUBLIC_KEY/SECRET_KEY every call here is a
no-op apart from the structured summary log line, so tests and local dev need
no account.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from courtside.config import get_settings

if TYPE_CHECKING:
    from anthropic.types import Message
    from langfuse import Langfuse

logger = logging.getLogger(__name__)


@lru_cache
def get_langfuse() -> Langfuse | None:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        environment=settings.env,
        release=settings.git_sha,
        # Seconds per export request; keeps a Langfuse outage from pinning Lambda.
        timeout=3,
    )


def _jsonable(value: Any) -> Any:
    """SDK pydantic objects (content blocks, messages) to plain JSON data."""
    return json.loads(json.dumps(value, default=_default))


def _default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    return str(obj)


@dataclass
class _Generation:
    span: Any
    _saw_first_token: bool = False

    def first_token(self) -> None:
        if self.span is not None and not self._saw_first_token:
            self.span.update(completion_start_time=datetime.now(UTC))
        self._saw_first_token = True

    def end(self, message: Message) -> None:
        if self.span is None:
            return
        u = message.usage
        self.span.update(
            output=_jsonable(message.content),
            usage_details={
                "input": u.input_tokens,
                "output": u.output_tokens,
                "cache_read_input_tokens": u.cache_read_input_tokens or 0,
                "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
            },
            metadata={"stop_reason": message.stop_reason},
        )


@dataclass
class TurnTrace:
    """Handle for one chat turn. `trace_id` is None when tracing is off."""

    root: Any = None
    trace_id: str | None = None
    rounds: int = 0
    tool_calls: list[str] = field(default_factory=list)
    tool_errors: int = 0
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input": 0,
            "output": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    )
    stop_reason: str | None = None
    outcome: str = "ok"

    @contextmanager
    def generation(
        self, *, model: str, system: Any, messages: Any, params: dict[str, Any]
    ) -> Iterator[_Generation]:
        self.rounds += 1
        span = None
        if self.root is not None:
            span = self.root.start_observation(
                name=f"llm.round.{self.rounds}",
                as_type="generation",
                model=model,
                model_parameters=params,
                input={"system": _jsonable(system), "messages": _jsonable(messages)},
            )
        gen = _Generation(span)
        try:
            yield gen
        finally:
            if span is not None:
                span.end()

    def record_message(self, message: Message) -> None:
        u = message.usage
        self.usage["input"] += u.input_tokens
        self.usage["output"] += u.output_tokens
        self.usage["cache_read_input_tokens"] += u.cache_read_input_tokens or 0
        self.usage["cache_creation_input_tokens"] += u.cache_creation_input_tokens or 0
        self.stop_reason = message.stop_reason

    def tool(self, name: str, tool_input: Any, content: str, is_error: bool) -> None:
        self.tool_calls.append(name)
        self.tool_errors += int(is_error)
        if self.root is None:
            return
        try:
            output: Any = json.loads(content)
        except ValueError:
            output = content
        span = self.root.start_observation(
            name=name,
            as_type="tool",
            input=_jsonable(tool_input),
            output=output,
            level="ERROR" if is_error else "DEFAULT",
        )
        span.end()

    def finish(self, output: str) -> None:
        summary = {
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "stop_reason": self.stop_reason,
            "outcome": self.outcome,
            "usage": self.usage,
        }
        logger.info("chat turn %s", json.dumps({"trace_id": self.trace_id, **summary}))
        if self.root is not None:
            self.root.update(
                output=output,
                metadata=summary,
                level="ERROR" if self.outcome == "error" else "DEFAULT",
            )


@asynccontextmanager
async def chat_turn(
    *, player_id: str, user_message: str, model: str, prompt_version: str
) -> AsyncIterator[TurnTrace]:
    client = get_langfuse()
    if client is None:
        yield TurnTrace()
        return

    from langfuse import propagate_attributes

    trace_id = client.create_trace_id()
    try:
        with (
            client.start_as_current_observation(
                trace_context={"trace_id": trace_id},
                name="chat.turn",
                as_type="agent",
                input=user_message,
                version=prompt_version,
            ) as root,
            propagate_attributes(
                user_id=player_id,
                version=prompt_version,
                tags=["chat"],
                trace_name="chat.turn",
                metadata={"model": model},
            ),
        ):
            yield TurnTrace(root=root, trace_id=trace_id)
    finally:
        # Lambda freezes the instance once the response ends; export now or lose it.
        await asyncio.to_thread(client.flush)


def record_feedback(trace_id: str, score: int, comment: str | None) -> None:
    client = get_langfuse()
    if client is None:
        logger.info("chat feedback %s", json.dumps({"trace_id": trace_id, "score": score}))
        return
    client.create_score(
        name="user_feedback",
        value=score,
        trace_id=trace_id,
        data_type="NUMERIC",
        comment=comment,
    )
    client.flush()
