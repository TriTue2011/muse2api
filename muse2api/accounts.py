"""Account pool: one persistent Gateway per cookie set, serialized per account.

The upstream chat history is shared per account (main chat), so concurrent
requests on the same account are serialized with a lock. Add more accounts
for parallelism — the pool round-robins over healthy ones.
"""

from __future__ import annotations

import logging
import secrets
import threading

from .config import AccountConfig
from .upstream.protocol import AuthError, Gateway, GatewayError

log = logging.getLogger("muse2api.accounts")


class Account:
    def __init__(self, cfg: AccountConfig):
        self.name = cfg.name
        self.cookies = cfg.cookies
        self.node_id = secrets.token_hex(8)
        self.lock = threading.Lock()
        self._gw: Gateway | None = None
        self.healthy = True
        self.last_error: str | None = None

    def ensure(self) -> Gateway:
        """Return a live Gateway, (re)connecting if needed. Caller holds lock."""
        if self._gw is not None:
            return self._gw
        log.info("account %s: connecting to muse.ai gateway", self.name)
        gw = Gateway(self.cookies)  # blocking: HTTPS bootstrap + WS + Noise
        self._gw = gw
        self.healthy = True
        self.last_error = None
        return gw

    def drop(self, reason: str):
        log.warning("account %s: dropping connection (%s)", self.name, reason)
        gw, self._gw = self._gw, None
        if gw is not None:
            try:
                gw.close()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def mark_auth_failed(self, reason: str):
        self.healthy = False
        self.last_error = reason
        self.drop(reason)


class Pool:
    def __init__(self, configs: list[AccountConfig]):
        if not configs:
            raise ValueError("no accounts configured (set MUSE_COOKIES or MUSE_COOKIES_FILE)")
        self.accounts = [Account(c) for c in configs]
        self._next = 0
        self._pick_lock = threading.Lock()

    def acquire(self) -> Account:
        """Round-robin pick of a healthy account; blocks on its lock."""
        with self._pick_lock:
            n = len(self.accounts)
            for _ in range(n):
                acc = self.accounts[self._next % n]
                self._next += 1
                if acc.healthy and acc.lock.acquire(blocking=False):
                    return acc
            # All busy (or unhealthy): wait on the next healthy one.
            for _ in range(n):
                acc = self.accounts[self._next % n]
                self._next += 1
                if acc.healthy:
                    acc.lock.acquire()
                    return acc
            # Every account unhealthy.
            raise AuthError("all accounts unhealthy: " +
                            "; ".join(f"{a.name}: {a.last_error}" for a in self.accounts))

    def release(self, acc: Account):
        acc.lock.release()

    def status(self) -> list[dict]:
        return [{"name": a.name, "healthy": a.healthy,
                 "connected": a._gw is not None,
                 "last_error": a.last_error} for a in self.accounts]
