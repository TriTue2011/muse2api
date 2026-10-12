"""CLI: serve | login | logout | models

- ``python -m muse2api`` / ``serve`` — start the gateway.
- ``python -m muse2api login`` — OAuth device flow: prints a user code
  and URL, you approve in your own browser, the minted Model API key is
  stored locally. No password or cookie is ever asked for.
- ``python -m muse2api logout`` — delete the stored key.
- ``python -m muse2api models`` — list models via the meta driver.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
import uvicorn

from . import __version__
from .app import create_app
from .auth import device
from .auth.device import DeviceDenied, DeviceExpired, DeviceFlowError, MintError
from .auth.keystore import KeyStore
from .config import Settings
from .drivers.meta import MetaDriver


def _keystore(settings: Settings) -> KeyStore:
    return KeyStore(settings.data_dir / "meta_key.json")


def cmd_serve(settings: Settings) -> int:
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
    return 0


def cmd_login(settings: Settings) -> int:
    store = _keystore(settings)

    async def _run() -> int:
        async with httpx.AsyncClient() as client:
            def on_code(d: device.DeviceAuthorization) -> None:
                print("\nOpen this URL in your browser and approve the request:")
                print(f"  {d.verification_uri}")
                print(f"Enter code: {d.user_code}\n")
                print("Waiting for approval...", flush=True)

            try:
                creds = await device.login(client, on_code)
            except DeviceDenied:
                print("Login denied in the browser.", file=sys.stderr)
                return 1
            except DeviceExpired:
                print("The code expired before approval. Try again.", file=sys.stderr)
                return 1
            except MintError as e:
                print(f"Could not mint an API key: {e}", file=sys.stderr)
                if e.action_url:
                    print(f"Complete setup at: {e.action_url}", file=sys.stderr)
                return 1
            except DeviceFlowError as e:
                print(f"Login failed: {e}", file=sys.stderr)
                return 1
            store.save(creds)
            print("Done. Meta API key stored locally and will refresh automatically.")
            return 0

    return asyncio.run(_run())


def cmd_logout(settings: Settings) -> int:
    _keystore(settings).clear()
    print("Stored Meta key deleted.")
    return 0


def cmd_models(settings: Settings) -> int:
    async def _run() -> int:
        driver = MetaDriver(
            _keystore(settings),
            static_key=settings.meta_api_key,
            timeout=settings.upstream_timeout,
        )
        await driver.startup()
        try:
            for m in await driver.list_models():
                print(m.id)
        finally:
            await driver.shutdown()
        return 0

    try:
        return asyncio.run(_run())
    except Exception as e:  # noqa: BLE001 - CLI surface
        print(f"error: {e}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="muse2api", description=f"muse2api {__version__} — Meta Model API gateway"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "login", "logout", "models"],
    )
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "serve":
        return cmd_serve(settings)
    if args.command == "login":
        return cmd_login(settings)
    if args.command == "logout":
        return cmd_logout(settings)
    return cmd_models(settings)


if __name__ == "__main__":
    raise SystemExit(main())
