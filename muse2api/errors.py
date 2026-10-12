"""Error hierarchy.

Every error maps to an HTTP status and an OpenAI-style error body::

    {"error": {"message": ..., "type": ..., "code": ...}}
"""
from __future__ import annotations

from typing import Any


class Muse2APIError(Exception):
    status_code: int = 500
    error_type: str = "server_error"
    code: str = "internal_error"
    retryable: bool = False

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        if code:
            self.code = code

    def to_body(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "code": self.code,
            }
        }


# --- client side -----------------------------------------------------------
class InvalidRequest(Muse2APIError):
    status_code = 400
    error_type = "invalid_request_error"
    code = "invalid_request"


class Unauthorized(Muse2APIError):
    status_code = 401
    error_type = "authentication_error"
    code = "invalid_api_key"


class Forbidden(Muse2APIError):
    status_code = 403
    error_type = "authentication_error"
    code = "forbidden"


class NotFound(Muse2APIError):
    status_code = 404
    error_type = "invalid_request_error"
    code = "not_found"


class Unsupported(Muse2APIError):
    """No official Meta API exists for this feature.

    The ``alternative`` text suggests the officially supported way to
    achieve something similar.
    """

    status_code = 501
    error_type = "not_supported"
    code = "unsupported_feature"

    def __init__(self, message: str = "", *, alternative: str = "") -> None:
        hint = f" Alternative: {alternative}" if alternative else ""
        super().__init__(message + hint)


class NoUpstreamCredential(Muse2APIError):
    """The server has no Meta API key (static or minted)."""

    status_code = 503
    error_type = "server_error"
    code = "upstream_not_configured"
    retryable = True

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "No Meta API key configured. Set META_API_KEY, or run "
            "'python -m muse2api login' to mint one via Meta's OAuth device flow."
        )


# --- upstream (api.meta.ai) -------------------------------------------------
class UpstreamError(Muse2APIError):
    status_code = 502
    error_type = "upstream_error"
    code = "upstream_error"
    retryable = True


class UpstreamAuthError(UpstreamError):
    """Upstream rejected the API key."""

    code = "upstream_auth_failed"
    retryable = False


class UpstreamRateLimit(UpstreamError):
    status_code = 429
    code = "upstream_rate_limited"
    retryable = True


class UpstreamTimeout(UpstreamError):
    status_code = 504
    code = "upstream_timeout"
    retryable = True


class UpstreamBadResponse(UpstreamError):
    """Upstream answered with something we cannot parse."""

    code = "upstream_bad_response"
    retryable = False
