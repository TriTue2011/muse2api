"""Configuration: everything comes from environment variables.

See ``.env.example`` for the full list.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """Runtime settings, built from the environment."""

    host: str = "127.0.0.1"
    port: int = 18610
    driver: str = "mock"  # mock | meta
    api_key: str = ""  # Bearer token protecting THIS service
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    meta_api_key: str = ""  # static upstream key (META_API_KEY / MODEL_API_KEY)
    upstream_timeout: float = 60.0
    chat_timeout: float = 300.0
    image_timeout: float = 240.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(_env("MUSE2API_DATA_DIR", "./data"))
        data_dir.mkdir(parents=True, exist_ok=True)

        api_key = _env("MUSE2API_KEY", "")
        if not api_key:
            key_file = data_dir / "api_key"
            if key_file.exists():
                api_key = key_file.read_text(encoding="utf-8").strip()
            if not api_key:
                api_key = "m2a_" + secrets.token_urlsafe(32)
                key_file.write_text(api_key, encoding="utf-8")

        meta_key = _env("META_API_KEY", "") or _env("MODEL_API_KEY", "")

        return cls(
            host=_env("MUSE2API_HOST", "127.0.0.1"),
            port=_env_int("MUSE2API_PORT", 18610),
            driver=_env("MUSE2API_DRIVER", "mock").lower(),
            api_key=api_key,
            data_dir=data_dir,
            meta_api_key=meta_key,
            upstream_timeout=_env_float("MUSE2API_TIMEOUT", 60.0),
            chat_timeout=_env_float("MUSE2API_CHAT_TIMEOUT", 300.0),
            image_timeout=_env_float("MUSE2API_IMAGE_TIMEOUT", 240.0),
            log_level=_env("MUSE2API_LOG_LEVEL", "INFO").upper(),
        )
