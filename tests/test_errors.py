"""Error -> HTTP status + OpenAI-style body mapping."""
import pytest

from muse2api.errors import (
    InvalidRequest,
    NoUpstreamCredential,
    NotFound,
    Unauthorized,
    Unsupported,
    UpstreamAuthError,
    UpstreamError,
    UpstreamRateLimit,
    UpstreamTimeout,
)


@pytest.mark.parametrize(
    "exc,status",
    [
        (InvalidRequest("bad"), 400),
        (Unauthorized("nope"), 401),
        (NotFound("gone"), 404),
        (Unsupported("nope", alternative="do X"), 501),
        (NoUpstreamCredential(), 503),
        (UpstreamError("boom"), 502),
        (UpstreamAuthError("bad key"), 502),
        (UpstreamRateLimit("slow"), 429),
        (UpstreamTimeout("slow"), 504),
    ],
)
def test_status_codes(exc, status):
    assert exc.status_code == status


def test_body_shape():
    body = InvalidRequest("bad input").to_body()
    assert set(body) == {"error"}
    assert body["error"]["message"] == "bad input"
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "invalid_request"


def test_unsupported_carries_alternative():
    err = Unsupported("video is out", alternative="use the web app")
    assert "use the web app" in err.message
    assert err.to_body()["error"]["code"] == "unsupported_feature"


def test_no_credential_guides_setup():
    err = NoUpstreamCredential()
    assert "META_API_KEY" in err.message
    assert "login" in err.message


def test_upstream_auth_not_retryable():
    assert UpstreamAuthError("x").retryable is False
    assert UpstreamError("x").retryable is True
