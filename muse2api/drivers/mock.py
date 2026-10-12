"""Mock driver: deterministic offline responses for development and tests.

Makes no network calls and needs no credentials.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from .base import DriverCapabilities, ModelInfo, MuseDriver

_MOCK_MODELS = [
    "muse-spark-1.3",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
    "muse-image-1.0",
    "muse-voice-transcribe-1.0",
    "sam-3.1",
]

_MOCK_TEXT = (
    "[mock driver] This is a deterministic offline reply. "
    "Set MUSE2API_DRIVER=meta and provide a Meta API key for real responses."
)


def _last_user_text(body: dict[str, Any]) -> str:
    for msg in reversed(body.get("messages", [])):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):  # multipart content
                return " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            return str(content)
    return ""


class MockDriver(MuseDriver):
    name = "mock"
    capabilities = DriverCapabilities(
        chat=True, responses=True, images=True, image_edit=False
    )

    async def list_models(self) -> list[ModelInfo]:
        now = int(time.time())
        return [ModelInfo(id=m, created=now) for m in _MOCK_MODELS]

    async def chat_complete(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        model = body.get("model", "muse-spark-1.3")
        text = f"{_MOCK_TEXT} (echo: {_last_user_text(body)[:120]!r})"
        now = int(time.time())
        return {
            "id": f"chatcmpl-mock-{now}",
            "object": "chat.completion",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    async def chat_stream(
        self, body: dict[str, Any], timeout: float
    ) -> AsyncIterator[str]:
        response = await self.chat_complete(body, timeout)
        text = response["choices"][0]["message"]["content"]
        for word in text.split(" "):
            yield word + " "

    async def responses_create(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        model = body.get("model", "muse-spark-1.3")
        now = int(time.time())
        return {
            "id": f"resp-mock-{now}",
            "object": "response",
            "created_at": now,
            "model": model,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": _MOCK_TEXT}],
                }
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }

    async def generate_image(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        now = int(time.time())
        return {
            "created": now,
            "data": [
                {
                    "url": "https://example.invalid/mock-image.png",
                    "revised_prompt": body.get("prompt", ""),
                }
            ],
        }
