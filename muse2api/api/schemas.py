"""OpenAI-compatible request schemas (pydantic)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _AllowExtra(BaseModel):
    model_config = ConfigDict(extra="allow")


class ChatMessage(_AllowExtra):
    role: str
    content: Any


class ChatCompletionRequest(_AllowExtra):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class ResponsesRequest(_AllowExtra):
    model: str = "muse-spark-1.3"
    input: Any
    stream: bool = False
    max_output_tokens: int | None = None


class ImageGenerationRequest(_AllowExtra):
    prompt: str
    model: str = "muse-image-1.0"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    response_format: str | None = None
