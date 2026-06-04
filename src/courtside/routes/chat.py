import json
from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from courtside.anthropic_client import stream_chat_response
from courtside.auth.deps import get_current_player
from courtside.db.models import Player
from courtside.db.session import get_db
from courtside.routes import CamelRouter
from courtside.schemas.chat import ChatRequest
from courtside.services.chat import build_chat_context, build_system_prompt

router = CamelRouter(tags=["chat"])


async def _sse_stream(deltas: AsyncIterator[str]) -> AsyncIterator[str]:
    async for delta in deltas:
        payload = json.dumps({"text": delta}, separators=(",", ":"))
        yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/chat")
def chat(
    payload: ChatRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    context = build_chat_context(db, player)
    system_prompt = build_system_prompt(context)
    deltas = stream_chat_response(
        system_prompt,
        [{"role": m.role, "content": m.content} for m in payload.messages],
    )
    return StreamingResponse(_sse_stream(deltas), media_type="text/event-stream")
