"""OAuth device flow against a mocked Meta (no network)."""
import httpx
import pytest

from muse2api.auth import device
from muse2api.auth.device import DeviceDenied, DeviceExpired


def _transport(poll_responses):
    calls = {"poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "device/authorization" in url:
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "UC-123",
                    "verification_uri_complete": "https://auth.meta.com/activate?c=x",
                    "interval": 0.01,
                    "expires_in": 60,
                },
            )
        if "device/token" in url:
            calls["poll"] += 1
            spec = poll_responses[min(calls["poll"] - 1, len(poll_responses) - 1)]
            return httpx.Response(spec[0], json=spec[1])
        if "muse-code/key" in url:
            assert request.headers["authorization"] == "Bearer ident-xyz"
            assert request.headers["x-api-version"] == "1.0.0"
            return httpx.Response(200, json={"api_key": "mk-test-key"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_full_login_flow():
    transport = _transport(
        [
            (400, {"error": "authorization_pending"}),
            (200, {"access_token": "ident-xyz"}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        seen = {}
        creds = await device.login(
            client, lambda d: seen.update(code=d.user_code, uri=d.verification_uri)
        )
    assert creds.access == "mk-test-key"
    assert creds.refresh == "ident-xyz"
    assert creds.expires_at > 0
    assert seen["code"] == "UC-123"
    assert seen["uri"].startswith("https://")


async def test_slow_down_then_success():
    transport = _transport(
        [
            (400, {"error": "slow_down"}),
            (200, {"access_token": "ident-xyz"}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as client:
        creds = await device.login(client, lambda d: None)
    assert creds.access == "mk-test-key"


async def test_denied_raises():
    transport = _transport([(400, {"error": "access_denied"})])
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DeviceDenied):
            await device.login(client, lambda d: None)


async def test_expired_token_raises():
    transport = _transport([(400, {"error": "expired_token"})])
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DeviceExpired):
            await device.login(client, lambda d: None)


async def test_mint_without_api_key_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"action_url": "https://example.invalid/setup"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(device.MintError) as ei:
            await device.mint_api_key(client, "ident-xyz")
    assert ei.value.action_url == "https://example.invalid/setup"
