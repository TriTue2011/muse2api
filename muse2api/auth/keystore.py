"""Persistence + refresh for OAuth-minted Meta API keys.

Keys are stored as JSON in the data dir (``meta_key.json``)::

    {"access": "<MODEL_API_KEY>", "refresh": "<identity token>",
     "expires_at": 1234567890.0}

On server start (or when a key expires), :func:`ensure_fresh_key` re-mints
a key from the stored identity token — the user only runs the device
flow once.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from ..errors import NoUpstreamCredential
from .device import Credentials, mint_api_key

log = logging.getLogger("muse2api.keystore")


@dataclass
class StoredKey:
    access: str
    refresh: str
    expires_at: float

    @property
    def fresh(self) -> bool:
        # 5-minute safety margin so a key never dies mid-request.
        return bool(self.access) and self.expires_at > time.time() + 300


class KeyStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StoredKey | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            key = StoredKey(
                access=str(data.get("access", "")),
                refresh=str(data.get("refresh", "")),
                expires_at=float(data.get("expires_at", 0)),
            )
            return key if key.access else None
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def save(self, creds: Credentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(creds), indent=2), encoding="utf-8"
        )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


async def ensure_fresh_key(
    client: httpx.AsyncClient,
    keystore: KeyStore,
    static_key: str = "",
) -> str:
    """Return a usable Meta API key.

    Precedence: static env key -> fresh minted key -> re-mint from the
    stored identity token -> raise :class:`NoUpstreamCredential`.
    """
    if static_key.strip():
        return static_key.strip()

    stored = keystore.load()
    if stored and stored.fresh:
        return stored.access

    if stored and stored.refresh.strip():
        try:
            log.info("Re-minting expired Meta API key from stored identity token")
            new_key = await mint_api_key(client, stored.refresh)
            creds = Credentials(
                access=new_key,
                refresh=stored.refresh,
                expires_at=time.time() + 24 * 60 * 60,
            )
            keystore.save(creds)
            return new_key
        except Exception as e:  # noqa: BLE001 - fall through to the setup error
            log.warning("Key re-mint failed: %s", e)

    raise NoUpstreamCredential()
