"""Driver interface: the only layer that knows how to talk to an upstream.

A driver turns OpenAI-shaped request dicts into upstream calls. HTTP
framing (SSE, status codes), auth of *this* service and error mapping to
the OpenAI wire format all live above this layer, so a new upstream only
needs to implement this class.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..errors import Unsupported


@dataclass(frozen=True)
class ModelInfo:
    id: str
    owned_by: str = "meta"
    created: int = 0


@dataclass(frozen=True)
class DriverCapabilities:
    chat: bool = False
    responses: bool = False
    images: bool = False
    image_edit: bool = False


class MuseDriver(ABC):
    name: str = "base"
    capabilities: DriverCapabilities = DriverCapabilities()

    async def startup(self) -> None:
        """Acquire long-lived resources (HTTP client, ...)."""

    async def shutdown(self) -> None:
        """Release resources acquired in :meth:`startup`."""

    async def health(self) -> dict[str, Any]:
        return {"driver": self.name, "ok": True}

    # -- models ----------------------------------------------------------
    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return the models this driver can serve."""

    async def get_model(self, model_id: str) -> ModelInfo | None:
        """Return one model, or None if unknown."""
        for m in await self.list_models():
            if m.id == model_id:
                return m
        return None

    async def service_status(self) -> dict[str, Any]:
        """Upstream service status (mirrors GET /v1/status)."""
        return {"status": "ok", "driver": self.name}

    # -- chat ------------------------------------------------------------
    @abstractmethod
    async def chat_complete(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        """Non-streaming ``/v1/chat/completions``. Returns an OpenAI-shaped dict."""

    def chat_stream(
        self, body: dict[str, Any], timeout: float
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas (implementations are async generators)."""
        raise Unsupported(f"driver '{self.name}' does not support chat streaming")

    # -- responses API ---------------------------------------------------
    async def responses_create(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        raise Unsupported(f"driver '{self.name}' does not support the Responses API")

    # -- images ----------------------------------------------------------
    async def generate_image(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        raise Unsupported(f"driver '{self.name}' does not support image generation")

    async def edit_image_passthrough(
        self, content: bytes, content_type: str, timeout: float
    ) -> Any:
        """Transparent proxy for ``POST /v1/images/edits`` (raw body)."""
        raise Unsupported(f"driver '{self.name}' does not support image edits")
