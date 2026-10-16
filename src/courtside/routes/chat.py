import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from anthropic.types import MessageParam, TextBlockParam
from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from courtside.anthropic_client import (
    SONNET_MODEL,
    RunTool,
    TextDelta,
    stream_chat_events,
)
from courtside.auth.deps import get_current_player
from courtside.auth.tokens import (
    InvalidTokenError,
    create_feedback_token,
    decode_feedback_token,
)
from courtside.db.models import Player
from courtside.db.session import get_db
from courtside.errors import APIError, is_database_resuming
from courtside.observability import chat_turn, record_feedback
from courtside.routes import CamelRouter
from courtside.schemas.chat import ChatFeedback, ChatRequest
from courtside.services.chat import PROMPT_VERSION, build_chat_context, build_system_prompt
from courtside.services.chat_tools import ToolOutcome, execute_tool, tool_definitions

logger = logging.getLogger(__name__)

router = CamelRouter(tags=["chat"])

_ERROR_TEXT = "\n\nSorry, something went wrong answering that. Please try again."


def _sse(payload: dict[str, str]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _tool_runner(db: Session, player: Player) -> RunTool:
    """Bind tool execution to this request's player and DB session."""

    async def run(name: str, tool_input: Any) -> ToolOutcome:
        try:
            # SQLAlchemy is sync; keep the event loop free while it runs.
            return await asyncio.to_thread(execute_tool, name, tool_input, db, player)
        except Exception as exc:
            db.rollback()
            if is_database_resuming(exc):
                message = "The database is waking up. Wait a few seconds and try again."
            else:
                logger.exception("chat tool %s failed", name)
                message = "Internal error while running this tool."
            return ToolOutcome(json.dumps({"error": message}), True)

    return run


async def _chat_stream(
    *,
    system: list[TextBlockParam],
    messages: list[MessageParam],
    run_tool: RunTool,
    player: Player,
    user_message: str,
) -> AsyncIterator[str]:
    async with chat_turn(
        player_id=str(player.id),
        user_message=user_message,
        model=SONNET_MODEL,
        prompt_version=PROMPT_VERSION,
    ) as trace:
        if trace.trace_id is not None:
            yield _sse({"feedback": create_feedback_token(trace.trace_id, player.id)})
        parts: list[str] = []
        try:
            async for event in stream_chat_events(
                system=system,
                messages=messages,
                tools=tool_definitions(),  # type: ignore[arg-type]
                run_tool=run_tool,
                trace=trace,
            ):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield _sse({"text": event.text})
                else:
                    yield _sse({"status": event.text})
        except Exception:
            # The 200 and earlier chunks are already sent, so finish the stream
            # with a readable message instead of dropping the connection.
            logger.exception("chat turn failed")
            trace.outcome = "error"
            parts.append(_ERROR_TEXT)
            yield _sse({"text": _ERROR_TEXT})
        trace.finish("".join(parts))
        # [DONE] goes out before chat_turn exits and flushes traces, so a slow
        # or unreachable Langfuse never delays the end of the answer.
        yield "data: [DONE]\n\n"


@router.post("/api/chat")
def chat(
    payload: ChatRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    context = build_chat_context(db, player)
    messages: list[MessageParam] = [
        {"role": m.role, "content": m.content} for m in payload.messages
    ]
    stream = _chat_stream(
        system=build_system_prompt(context),
        messages=messages,
        run_tool=_tool_runner(db, player),
        player=player,
        user_message=payload.messages[-1].content,
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@router.post("/api/chat/feedback")
def chat_feedback(
    payload: ChatFeedback,
    player: Player = Depends(get_current_player),
) -> dict[str, str]:
    try:
        trace_id, player_id = decode_feedback_token(payload.token)
    except InvalidTokenError as exc:
        raise APIError(400, "invalid_feedback_token", "Feedback token is invalid") from exc
    if player_id != player.id:
        raise APIError(403, "forbidden", "This answer belongs to another player")
    record_feedback(trace_id, payload.score, payload.comment)
    return {}
