"""Auth for this service: Bearer <MUSE2API_KEY>."""
from __future__ import annotations

import secrets

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..errors import Unauthorized

_bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    settings = request.app.state.settings
    token = creds.credentials if creds else ""
    if not token or not secrets.compare_digest(token, settings.api_key):
        raise Unauthorized("invalid or missing API key")
    return token
