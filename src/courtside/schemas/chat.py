from typing import Literal

from pydantic import Field

from courtside.schemas.base import CamelModel


class ChatMessage(CamelModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(CamelModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
