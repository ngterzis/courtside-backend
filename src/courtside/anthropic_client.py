import json
from typing import Any

import anthropic

from courtside.config import get_settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"


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
