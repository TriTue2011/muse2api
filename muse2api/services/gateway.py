"""Service layer: owns the driver and delegates requests to it."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..auth.keystore import KeyStore
from ..config import Settings
from ..drivers.base import ModelInfo, MuseDriver
from ..drivers.meta import MetaDriver
from ..drivers.mock import MockDriver
from ..errors import InvalidRequest, Unsupported


def build_driver(settings: Settings) -> MuseDriver:
    if settings.driver == "meta":
        return MetaDriver(
            KeyStore(settings.data_dir / "meta_key.json"),
            static_key=settings.meta_api_key,
            timeout=settings.upstream_timeout,
        )
    if settings.driver == "mock":
        return MockDriver()
    raise InvalidRequest(
        f"unknown driver {settings.driver!r} (expected 'mock' or 'meta')"
    )


class Gateway:
    """Thin delegation + capability checks."""

    def __init__(self, driver: MuseDriver) -> None:
        self.driver = driver

    def _need(self, capability: str) -> None:
        if not getattr(self.driver.capabilities, capability, False):
            raise Unsupported(
                f"driver '{self.driver.name}' does not support '{capability}'",
                alternative="switch MUSE2API_DRIVER or use a supported endpoint "
                "(see GET /support)",
            )

    async def list_models(self) -> list[ModelInfo]:
        return await self.driver.list_models()

    async def get_model(self, model_id: str) -> ModelInfo | None:
        return await self.driver.get_model(model_id)

    async def service_status(self) -> dict[str, Any]:
        return await self.driver.service_status()

    async def chat_complete(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self._need("chat")
        return await self.driver.chat_complete(body, timeout)

    def chat_stream(
        self, body: dict[str, Any], timeout: float
    ) -> AsyncIterator[str]:
        self._need("chat")
        return self.driver.chat_stream(body, timeout)

    async def responses_create(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self._need("responses")
        return await self.driver.responses_create(body, timeout)

    async def generate_image(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self._need("images")
        return await self.driver.generate_image(body, timeout)
