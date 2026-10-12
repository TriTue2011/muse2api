"""Meta OAuth device flow (RFC 8628) + Model API key minting.

This mirrors the flow Meta's own Muse Code CLI uses:

1. ``POST https://auth.meta.com/oidc/device/authorization/``
   with ``{client_id}`` -> device code + user code + verification URL.
2. The user opens the verification URL in their own browser and approves.
   This module polls ``POST https://auth.meta.com/oidc/device/token/``
   until Meta returns an identity token. No password or cookie ever
   touches this code.
3. ``POST https://api.meta.ai/muse-code/key`` with the identity token
   as ``Bearer`` mints a Model API key usable at ``api.meta.ai/v1``.

Endpoint and parameter shapes below were observed in Meta's first-party
tooling (see pi-meta-oauth); the key-mint endpoint is not part of Meta's
published public docs, so :func:`mint_api_key` treats unexpected shapes
as errors instead of guessing.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

DEVICE_AUTHORIZATION_URL = "https://auth.meta.com/oidc/device/authorization/"
DEVICE_TOKEN_URL = "https://auth.meta.com/oidc/device/token/"
API_KEY_MINT_URL = "https://api.meta.ai/muse-code/key"
META_CLIENT_ID = "1031625952748946"
META_API_VERSION = "1.0.0"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Minted keys are refreshed daily, matching first-party behaviour.
KEY_REFRESH_INTERVAL_S = 24 * 60 * 60
REQUEST_TIMEOUT_S = 30.0


class DeviceFlowError(Exception):
    """Base class for device-flow failures."""


class DeviceDenied(DeviceFlowError):
    """The user denied the authorization request."""


class DeviceExpired(DeviceFlowError):
    """The device code expired before the user approved it."""


class MintError(DeviceFlowError):
    """Meta did not issue an API key."""

    def __init__(self, message: str, *, action_url: str | None = None) -> None:
        super().__init__(message)
        self.action_url = action_url


@dataclass
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    interval: float  # seconds between polls
    expires_in: float  # seconds until the code expires


@dataclass
class Credentials:
    access: str  # the Model API key
    refresh: str  # the identity token (used to mint fresh keys)
    expires_at: float  # epoch seconds


def _as_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


async def request_device_authorization(
    client: httpx.AsyncClient,
) -> DeviceAuthorization:
    """Start the flow. Returns the codes the user must approve."""
    try:
        resp = await client.post(
            DEVICE_AUTHORIZATION_URL,
            data={"client_id": META_CLIENT_ID},
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.TimeoutException as e:
        raise DeviceFlowError("Meta login request timed out") from e
    body = _as_json(resp)
    if resp.status_code >= 400:
        detail = body.get("error_description") or body.get("error") or resp.text
        raise DeviceFlowError(f"Meta login could not be started: {detail}")

    device_code = body.get("device_code") or ""
    user_code = body.get("user_code") or ""
    uri = body.get("verification_uri_complete") or body.get("verification_uri") or ""
    if not device_code.strip() or not user_code.strip() or not uri.startswith("http"):
        raise DeviceFlowError("Meta device authorization returned an incomplete response")

    def _seconds(value: Any, fallback: float) -> float:
        try:
            seconds = float(value)
            return seconds if seconds > 0 else fallback
        except (TypeError, ValueError):
            return fallback

    return DeviceAuthorization(
        device_code=device_code,
        user_code=user_code,
        verification_uri=uri,
        interval=max(1.0, _seconds(body.get("interval"), 5.0)),
        expires_in=_seconds(body.get("expires_in"), 900.0),
    )


async def poll_identity_token(
    client: httpx.AsyncClient,
    device: DeviceAuthorization,
    on_poll: Callable[[float], None] | None = None,
) -> str:
    """Poll until the user approves. Returns the identity token."""
    deadline = time.time() + device.expires_in
    interval = device.interval
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise DeviceExpired("Meta login request expired")
        await asyncio.sleep(min(interval, remaining))
        if on_poll:
            on_poll(max(0.0, deadline - time.time()))
        try:
            resp = await client.post(
                DEVICE_TOKEN_URL,
                data={
                    "grant_type": DEVICE_CODE_GRANT,
                    "device_code": device.device_code,
                    "client_id": META_CLIENT_ID,
                },
                timeout=min(REQUEST_TIMEOUT_S, max(1.0, deadline - time.time())),
            )
        except httpx.TimeoutException:
            # A stalled poll near the deadline means expiry.
            if time.time() >= deadline:
                raise DeviceExpired("Meta login request expired")
            continue
        body = _as_json(resp)
        if resp.status_code < 400 and body.get("access_token"):
            return str(body["access_token"])
        error = str(body.get("error", ""))
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5.0
            continue
        if error == "access_denied":
            raise DeviceDenied("Meta login was denied")
        if error == "expired_token":
            raise DeviceExpired("Meta login request expired")
        detail = body.get("error_description") or error or resp.text
        raise DeviceFlowError(f"Meta login failed: {detail}")


async def mint_api_key(client: httpx.AsyncClient, identity_token: str) -> str:
    """Exchange an identity token for a Model API key."""
    try:
        resp = await client.post(
            API_KEY_MINT_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {identity_token}",
                "Content-Type": "application/json",
                "x-api-version": META_API_VERSION,
            },
            content=b"{}",
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.TimeoutException as e:
        raise MintError("Meta API-key mint timed out") from e
    body = _as_json(resp)
    if resp.status_code >= 400:
        if resp.status_code in (401, 403):
            raise MintError(
                "Meta session expired; run 'python -m muse2api login' again"
            )
        detail = body.get("error_description") or body.get("error") or resp.text
        raise MintError(f"Meta API-key mint failed (HTTP {resp.status_code}): {detail}")
    api_key = body.get("api_key") or ""
    if not api_key.strip():
        raise MintError(
            "Meta did not issue an API key.",
            action_url=body.get("action_url"),
        )
    return str(api_key)


async def login(
    client: httpx.AsyncClient,
    on_device_code: Callable[[DeviceAuthorization], None],
    on_poll: Callable[[float], None] | None = None,
) -> Credentials:
    """Run the full flow: device code -> user approval -> minted API key."""
    device = await request_device_authorization(client)
    on_device_code(device)
    identity_token = await poll_identity_token(client, device, on_poll)
    api_key = await mint_api_key(client, identity_token)
    return Credentials(
        access=api_key,
        refresh=identity_token,
        expires_at=time.time() + KEY_REFRESH_INTERVAL_S,
    )
