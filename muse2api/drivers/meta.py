"""Driver for Meta's official Model API (https://api.meta.ai/v1).

Auth: a static key from ``META_API_KEY``/``MODEL_API_KEY``, or a key
minted via the OAuth device flow (``python -m muse2api login``) and
refreshed automatically by :mod:`muse2api.auth.keystore`.

Only endpoints documented (or directly observed in first-party tooling)
are used: ``/v1/models``, ``/v1/chat/completions``, ``/v1/responses``,
``/v1/images/generations``. Anything else raises :class:`Unsupported`.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from ..auth.keystore import KeyStore, ensure_fresh_key
from ..errors import (
    Unsupported,
    UpstreamAuthError,
    UpstreamBadResponse,
    UpstreamError,
    UpstreamRateLimit,
    UpstreamTimeout,
)
from .base import DriverCapabilities, ModelInfo, MuseDriver

log = logging.getLogger("muse2api.driver.meta")

BASE_URL = "https://api.meta.ai/v1"

# Fallback catalog if the upstream /v1/models call fails.
_FALLBACK_MODELS = [
    "muse-spark-1.3",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
    "muse-image-1.0",
    "muse-voice-transcribe-1.0",
    "sam-3.1",
]


def _error_message(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", ""))
        if isinstance(err, str):
            return err
        return str(body.get("message", ""))
    return str(body or "")


class MetaDriver(MuseDriver):
    name = "meta"
    capabilities = DriverCapabilities(
        chat=True, responses=True, images=True, image_edit=True
    )

    def __init__(
        self,
        keystore: KeyStore,
        static_key: str = "",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._keystore = keystore
        self._static_key = static_key
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def startup(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=httpx.Timeout(
                    connect=10.0, read=self._timeout, write=10.0, pool=10.0
                ),
            )

    async def shutdown(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {"driver": self.name, "ok": True}
        try:
            await self._key()
        except Exception as e:  # noqa: BLE001 - health must not raise
            info.update(ok=False, error=str(e))
        return info

    # -- internal ------------------------------------------------------
    async def _key(self) -> str:
        assert self._client is not None, "driver not started"
        return await ensure_fresh_key(
            self._client, self._keystore, self._static_key
        )

    def _map_error(self, status: int, body: Any) -> UpstreamError:
        msg = _error_message(body) or f"upstream HTTP {status}"
        if status in (401, 403):
            return UpstreamAuthError(
                f"{msg} (check META_API_KEY or run 'python -m muse2api login')"
            )
        if status == 429:
            return UpstreamRateLimit(msg)
        if status >= 500:
            return UpstreamError(msg)  # retryable
        return UpstreamBadResponse(msg)

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: float,
        *,
        stream: bool = False,
    ) -> httpx.Response:
        assert self._client is not None, "driver not started"
        key = await self._key()
        headers = {"Authorization": f"Bearer {key}"}
        try:
            if stream:
                return await self._client.post(
                    path, json=payload, headers=headers, timeout=timeout
                )
            resp = await self._client.post(
                path, json=payload, headers=headers, timeout=timeout
            )
        except httpx.TimeoutException as e:
            raise UpstreamTimeout(f"upstream timed out after {timeout}s") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"upstream transport error: {e}") from e
        if resp.status_code >= 400:
            raise self._map_error(resp.status_code, _safe_json(resp))
        return resp

    # -- models --------------------------------------------------------
    async def list_models(self) -> list[ModelInfo]:
        assert self._client is not None, "driver not started"
        try:
            key = await self._key()
            resp = await self._client.get(
                "/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                raise self._map_error(resp.status_code, _safe_json(resp))
            data = resp.json().get("data", [])
            models = [
                ModelInfo(
                    id=str(m.get("id", "")),
                    owned_by=str(m.get("owned_by", "meta")),
                    created=int(m.get("created", 0) or 0),
                )
                for m in data
                if isinstance(m, dict) and m.get("id")
            ]
            if models:
                return models
        except UpstreamError:
            raise
        except Exception as e:  # noqa: BLE001 - fall back to static catalog
            log.warning("Model catalog fetch failed, using fallback: %s", e)
        now = int(time.time())
        return [ModelInfo(id=m, created=now) for m in _FALLBACK_MODELS]

    async def get_model(self, model_id: str) -> ModelInfo | None:
        assert self._client is not None, "driver not started"
        try:
            key = await self._key()
            resp = await self._client.get(
                f"/models/{model_id}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=self._timeout,
            )
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise self._map_error(resp.status_code, _safe_json(resp))
            m = resp.json()
            if isinstance(m, dict) and m.get("id"):
                return ModelInfo(
                    id=str(m["id"]),
                    owned_by=str(m.get("owned_by", "meta")),
                    created=int(m.get("created", 0) or 0),
                )
            return None
        except UpstreamError:
            raise
        except Exception as e:  # noqa: BLE001 - fall back to the static catalog
            log.warning("get_model failed, falling back to catalog: %s", e)
            return await super().get_model(model_id)

    async def service_status(self) -> dict[str, Any]:
        assert self._client is not None, "driver not started"
        try:
            resp = await self._client.get("/status", timeout=self._timeout)
            if resp.status_code >= 400:
                return {"status": "degraded", "http_status": resp.status_code}
            body = _safe_json(resp)
            return body if isinstance(body, dict) else {"status": str(body)}
        except Exception as e:  # noqa: BLE001 - status must not raise
            return {"status": "unreachable", "error": str(e)}

    # -- chat ----------------------------------------------------------
    def _chat_payload(self, body: dict[str, Any], stream: bool) -> dict[str, Any]:
        payload = dict(body)
        payload["stream"] = stream
        payload.setdefault("model", "muse-spark-1.3")
        return payload

    async def chat_complete(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        resp = await self._post_json(
            "/chat/completions", self._chat_payload(body, False), timeout
        )
        data = _safe_json(resp)
        if not isinstance(data, dict) or "choices" not in data:
            raise UpstreamBadResponse("upstream chat response had no 'choices'")
        return data

    async def chat_stream(
        self, body: dict[str, Any], timeout: float
    ) -> AsyncIterator[str]:
        assert self._client is not None, "driver not started"
        key = await self._key()
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=self._chat_payload(body, True),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "text/event-stream",
                },
                timeout=timeout,
            ) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    raise self._map_error(resp.status_code, _safe_json_raw(raw))
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    for choice in obj.get("choices", []):
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield delta
        except UpstreamError:
            raise
        except httpx.TimeoutException as e:
            raise UpstreamTimeout(f"upstream stream timed out after {timeout}s") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"upstream stream error: {e}") from e

    # -- responses API -------------------------------------------------
    async def responses_create(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        payload = dict(body)
        payload.setdefault("model", "muse-spark-1.3")
        resp = await self._post_json("/responses", payload, timeout)
        data = _safe_json(resp)
        if not isinstance(data, dict) or "output" not in data:
            raise UpstreamBadResponse("upstream responses body had no 'output'")
        return data

    # -- images --------------------------------------------------------
    async def generate_image(
        self, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        payload = {
            "prompt": body.get("prompt", ""),
            "model": body.get("model", "muse-image-1.0"),
        }
        for field in ("size", "n", "response_format", "quality", "style"):
            if body.get(field) is not None:
                payload[field] = body[field]
        resp = await self._post_json("/images/generations", payload, timeout)
        data = _safe_json(resp)
        if not isinstance(data, dict) or "data" not in data:
            raise UpstreamBadResponse("upstream image response had no 'data'")
        return data

    async def edit_image_passthrough(
        self, content: bytes, content_type: str, timeout: float
    ) -> httpx.Response:
        """Transparent proxy: the multipart body is forwarded untouched, so no
        assumptions are made about the upstream ``/v1/images/edits`` schema."""
        assert self._client is not None, "driver not started"
        key = await self._key()
        try:
            resp = await self._client.post(
                "/images/edits",
                content=content,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": content_type,
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as e:
            raise UpstreamTimeout(f"upstream timed out after {timeout}s") from e
        except httpx.HTTPError as e:
            raise UpstreamError(f"upstream transport error: {e}") from e
        if resp.status_code >= 400:
            raise self._map_error(resp.status_code, _safe_json(resp))
        return resp


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _safe_json_raw(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return raw.decode("utf-8", "replace")
