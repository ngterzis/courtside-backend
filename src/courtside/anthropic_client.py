import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from courtside.config import get_settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"


def generate_archetype_explanation(
    primary: str,
    secondary: str,
    receipt: list[dict[str, Any]],
) -> str:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return f"Profiled as a {primary} / {secondary} based on season averages."

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=200,
        system=(
            "You are a basketball analytics assistant. Write 1–2 sentences "
            f"explaining why this player is a {primary} / {secondary}. "
            "Be specific and reference their stats. No filler phrases."
        ),
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {"primary": primary, "secondary": secondary, "receipt": receipt}
                ),
            }
        ],
    )
    return "".join(
        getattr(block, "text", "")
        for block in message.content
        if getattr(block, "type", None) == "text"
    )


async def stream_chat_response(
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    settings = get_settings()
    if not settings.anthropic_api_key:
        async for word in _fallback_stream():
            yield word
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    async with client.messages.stream(
        model=SONNET_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _fallback_stream() -> AsyncIterator[str]:
    msg = (
        "Chat is not configured. Set ANTHROPIC_API_KEY to enable "
        "streaming responses from Claude."
    )
    for word in msg.split():
        await asyncio.sleep(0.02)
        yield word + " "
