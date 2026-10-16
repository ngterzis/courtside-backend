import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
)

from courtside.config import get_settings
from courtside.observability import TurnTrace
from courtside.services.chat_tools import ToolOutcome, status_for

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


# Tool rounds per chat turn. After this many, one last call runs with tools
# disabled so the model answers with what it has instead of looping.
MAX_TOOL_ROUNDS = 5
CHAT_MAX_TOKENS = 2048


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolStatus:
    text: str


ChatEvent = TextDelta | ToolStatus
RunTool = Callable[[str, Any], Awaitable[ToolOutcome]]


async def stream_chat_events(
    *,
    system: list[TextBlockParam],
    messages: list[MessageParam],
    tools: list[ToolParam],
    run_tool: RunTool,
    trace: TurnTrace,
) -> AsyncIterator[ChatEvent]:
    """Stream one chat turn, letting the model call tools between rounds.

    Text from every round is streamed as it arrives; between rounds a
    ToolStatus says what is being looked up. All tool results of a round go
    back in a single user message so the model keeps making parallel calls.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        async for word in _fallback_stream():
            yield TextDelta(word)
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    convo: list[MessageParam] = list(messages)
    emitted_text = False

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        params: dict[str, Any] = {"max_tokens": CHAT_MAX_TOKENS}
        if round_no == MAX_TOOL_ROUNDS:
            params["tool_choice"] = {"type": "none"}

        with trace.generation(
            model=SONNET_MODEL, system=system, messages=convo, params=params
        ) as gen:
            async with client.messages.stream(
                model=SONNET_MODEL,
                system=system,
                tools=tools,
                messages=convo,
                # Auto-cache the conversation so later tool rounds of this turn
                # re-read earlier rounds from cache. The static system block
                # carries its own breakpoint for the cross-request prefix.
                cache_control={"type": "ephemeral"},
                **params,
            ) as stream:
                first = True
                async for text in stream.text_stream:
                    if first:
                        gen.first_token()
                        # Separate this round's text from the previous round's.
                        if emitted_text:
                            yield TextDelta("\n\n")
                        first = False
                    emitted_text = True
                    yield TextDelta(text)
                message = await stream.get_final_message()
            gen.end(message)
        trace.record_message(message)

        if message.stop_reason != "tool_use":
            return

        tool_uses = [b for b in message.content if isinstance(b, ToolUseBlock)]
        yield ToolStatus(status_for([b.name for b in tool_uses]))

        results: list[ToolResultBlockParam] = []
        for block in tool_uses:
            outcome = await run_tool(block.name, block.input)
            trace.tool(block.name, block.input, outcome.content, outcome.is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": outcome.content,
                    "is_error": outcome.is_error,
                }
            )
        convo.append({"role": "assistant", "content": message.content})
        convo.append({"role": "user", "content": results})


async def _fallback_stream() -> AsyncIterator[str]:
    msg = (
        "Chat is not configured. Set ANTHROPIC_API_KEY to enable "
        "streaming responses from Claude."
    )
    for word in msg.split():
        await asyncio.sleep(0.02)
        yield word + " "
