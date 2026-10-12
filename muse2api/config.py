"""Settings loaded from environment variables / cookie files."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class AccountConfig:
    name: str
    cookies: str  # "a=b; c=d" cookie header value for muse.ai


@dataclass
class Settings:
    api_key: str = ""          # Bearer key protecting /v1/* (empty = no auth)
    host: str = "127.0.0.1"
    port: int = 8000
    accounts: list[AccountConfig] = field(default_factory=list)
    poll_interval: float = 2.0
    wait_s: float = 300.0
    quiet_s: float = 10.0
    model_name: str = "muse"


def _cookies_from_file(path: str) -> list[AccountConfig]:
    """Accept several shapes:
      - {"accounts": [{"name": .., "cookies": ".."}]}
      - {"cookies": {"a": "b", ..}}            (single account, JSON cookies)
      - {"a": "b", ..}                          (single account, JSON cookies)
      - raw "a=b; c=d" text                     (single account)
    """
    raw = open(path, encoding="utf-8").read().strip()
    if raw.startswith("{"):
        d = json.loads(raw)
        if isinstance(d.get("accounts"), list):
            out = []
            for i, a in enumerate(d["accounts"]):
                c = a.get("cookies", "")
                if isinstance(c, dict):
                    c = "; ".join(f"{k}={v}" for k, v in c.items())
                if c:
                    out.append(AccountConfig(name=a.get("name", f"acc{i+1}"),
                                             cookies=str(c)))
            return out
        c = d.get("cookies", d) if isinstance(d, dict) else {}
        if isinstance(c, dict):
            c = "; ".join(f"{k}={v}" for k, v in c.items())
        if c:
            return [AccountConfig(name="default", cookies=str(c))]
        return []
    # raw cookie header text (possibly multi-line Netscape jar — take last resort)
    lines = [ln.strip() for ln in raw.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    if any(";" in ln and "=" in ln for ln in lines):
        header = next(ln for ln in lines if ";" in ln and "=" in ln)
        return [AccountConfig(name="default", cookies=header)]
    if raw:
        return [AccountConfig(name="default", cookies=" ".join(raw.split()))]
    return []


def load_settings() -> Settings:
    s = Settings()
    s.api_key = os.environ.get("MUSE2API_KEY", "").strip()
    s.host = os.environ.get("MUSE2API_HOST", s.host)
    s.port = int(os.environ.get("MUSE2API_PORT", s.port))
    s.poll_interval = float(os.environ.get("MUSE2API_POLL_INTERVAL", s.poll_interval))
    s.wait_s = float(os.environ.get("MUSE2API_WAIT_S", s.wait_s))
    s.quiet_s = float(os.environ.get("MUSE2API_QUIET_S", s.quiet_s))
    s.model_name = os.environ.get("MUSE2API_MODEL", s.model_name)

    accounts: list[AccountConfig] = []
    cookie_file = os.environ.get("MUSE_COOKIES_FILE", "").strip()
    if cookie_file:
        accounts.extend(_cookies_from_file(cookie_file))
    single = os.environ.get("MUSE_COOKIES", "").strip()
    if single:
        accounts.append(AccountConfig(name="default", cookies=single))
    # MUSE_COOKIES_1, MUSE_COOKIES_2, ... for extra accounts
    i = 1
    while True:
        v = os.environ.get(f"MUSE_COOKIES_{i}", "").strip()
        if not v:
            break
        accounts.append(AccountConfig(name=f"acc{i}", cookies=v))
        i += 1
    s.accounts = accounts
    return s
