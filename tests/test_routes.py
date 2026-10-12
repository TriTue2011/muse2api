"""HTTP integration tests against the mock driver (no network)."""
import pytest
from fastapi.testclient import TestClient

from muse2api.app import create_app
from muse2api.config import Settings
from muse2api.drivers.mock import MockDriver

HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(api_key="test-key", data_dir=tmp_path, driver="mock")
    app = create_app(settings, MockDriver())
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_reports_mock_driver(client):
    r = client.get("/readyz", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["driver"] == "mock"


def test_auth_missing_is_401(client):
    r = client.get("/v1/models")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_auth_wrong_key_is_401(client):
    r = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_list_models(client):
    r = client.get("/v1/models", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert any(m["id"] == "muse-spark-1.3" for m in body["data"])


def test_chat_non_stream(client):
    r = client.post(
        "/v1/chat/completions",
        headers=HEADERS,
        json={"model": "muse-spark-1.3",
              "messages": [{"role": "user", "content": "hello"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"]


def test_chat_stream_sse(client):
    r = client.post(
        "/v1/chat/completions",
        headers=HEADERS,
        json={"model": "muse-spark-1.3",
              "messages": [{"role": "user", "content": "hello"}],
              "stream": True},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    text = r.text
    assert "data: [DONE]" in text
    assert '"object": "chat.completion.chunk"' in text


def test_chat_validation_error_is_400(client):
    r = client.post("/v1/chat/completions", headers=HEADERS, json={"model": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_responses_non_stream(client):
    r = client.post(
        "/v1/responses",
        headers=HEADERS,
        json={"model": "muse-spark-1.3", "input": "hello"},
    )
    assert r.status_code == 200
    assert r.json()["object"] == "response"


def test_responses_stream_is_501(client):
    r = client.post(
        "/v1/responses",
        headers=HEADERS,
        json={"model": "muse-spark-1.3", "input": "hello", "stream": True},
    )
    assert r.status_code == 501


def test_images_generations(client):
    r = client.post(
        "/v1/images/generations",
        headers=HEADERS,
        json={"prompt": "a red fox", "model": "muse-image-1.0"},
    )
    assert r.status_code == 200
    assert r.json()["data"][0]["url"]


def test_videos_unsupported(client):
    r = client.post("/v1/videos", headers=HEADERS, json={"prompt": "x"})
    assert r.status_code == 501
    assert "Alternative" in r.json()["error"]["message"]


def test_support_matrix(client):
    r = client.get("/support", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert any("/v1/chat/completions" in s for s in body["supported"])
    assert "/v1/videos*" in body["unsupported"]


def test_unknown_route_is_404(client):
    r = client.get("/v1/nope", headers=HEADERS)
    assert r.status_code == 404


def test_get_single_model(client):
    r = client.get("/v1/models/muse-spark-1.3", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "muse-spark-1.3"
    assert body["object"] == "model"


def test_get_unknown_model_is_404(client):
    r = client.get("/v1/models/nope-9", headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_service_status_no_auth(client):
    r = client.get("/v1/status")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
