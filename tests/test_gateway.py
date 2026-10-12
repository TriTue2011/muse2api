"""Unit tests for the gateway. The upstream muse.ai protocol is mocked —
live verification needs real cookies (see README)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from muse2api.accounts import Pool
from muse2api.config import AccountConfig, Settings
from muse2api.server import create_app
from muse2api.upstream import chat as chat_mod
from muse2api.upstream.chat import ChatSession, build_prompt, is_genuine_reply


# ── prompt building ────────────────────────────────────────────────────

def test_build_prompt_roles():
    p = build_prompt([
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Bye"},
    ])
    assert "System: Be brief." in p
    assert "User: Hi" in p
    assert "Assistant: Hello" in p
    assert p.endswith("User: Bye")


def test_build_prompt_multipart_and_empty():
    p = build_prompt([
        {"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "x"}},
        ]},
        {"role": "user", "content": "   "},
    ])
    assert p == "User: look"


# ── reply filtering ────────────────────────────────────────────────────

def _ev(seq, name, text, reply_to=None):
    e = {"seq": seq, "event_name": name,
         "payload": {"display_text": text}}
    if reply_to:
        e["reply_to_message_id"] = reply_to
    return e


def test_is_genuine_reply():
    assert is_genuine_reply(_ev(5, "message.assistant", "hi"), 4)
    assert not is_genuine_reply(_ev(4, "message.assistant", "hi"), 4)   # old
    assert not is_genuine_reply(_ev(5, "message.user", "hi"), 4)        # user
    assert not is_genuine_reply(_ev(5, "message.assistant", "hi", reply_to="m1"), 4)
    assert not is_genuine_reply(_ev(5, "message.assistant", ""), 4)     # empty


# ── fake upstream ──────────────────────────────────────────────────────

class FakeGateway:
    """Canned chat.history snapshots, one per call."""

    def __init__(self, histories):
        self._histories = histories
        self._i = 0
        self.sent = []

    def _open(self, method, body=None, **kw):
        self.sent.append((method, body))
        return 1

    def call_json(self, method, body=None, **kw):
        assert method == "chat.history"
        h = self._histories[min(self._i, len(self._histories) - 1)]
        self._i += 1
        return h


def _hist(*events):
    return {"chat_events": list(events)}


def test_chat_session_deltas():
    gw = FakeGateway([
        _hist(),                                                          # baseline
        _hist(_ev(5, "message.assistant", "Hello")),                      # first
        _hist(_ev(5, "message.assistant", "Hello world")),                # grows
        _hist(_ev(5, "message.assistant", "Hello world")),                # quiet…
        _hist(_ev(5, "message.assistant", "Hello world")),                # quiet…
    ])
    sess = ChatSession(gw, "node1", poll_interval=0.01, wait_s=5, quiet_s=0.03)
    deltas = list(sess.run("hi"))
    assert deltas == ["Hello", " world"], deltas
    method, body = gw.sent[0]
    assert method == "chat.stream"
    assert body["items"][0]["text"] == "hi"
    assert body["node_id"] == "node1"


def test_chat_session_timeout():
    gw = FakeGateway([_hist()] * 10)
    sess = ChatSession(gw, "node1", poll_interval=0.01, wait_s=0.1, quiet_s=0.01)
    with pytest.raises(TimeoutError):
        list(sess.run("hi"))


# ── FastAPI layer (ChatSession mocked) ──────────────────────────────────

class FakeChatSession:
    def __init__(self, *a, **kw):
        pass

    def run_collect(self, prompt):
        assert prompt
        return "mock reply"

    def run(self, prompt):
        yield "mock "
        yield "reply"


def _app(api_key="test-key"):
    settings = Settings(api_key=api_key, wait_s=5, quiet_s=0.1)
    pool = Pool([AccountConfig(name="a", cookies="x=1")])
    return create_app(settings, pool)


def test_models_and_auth():
    c = TestClient(_app())
    assert c.get("/v1/models").status_code == 401
    r = c.get("/v1/models", headers={"Authorization": "Bearer test-key"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data[0]["id"] == "muse"


def test_chat_nonstream_shape():
    c = TestClient(_app())
    h = {"Authorization": "Bearer test-key"}
    import muse2api.server as srv
    with patch.object(srv, "ChatSession", FakeChatSession), \
         patch.object(srv, "_ensure_gw", lambda acc: None):
        r = c.post("/v1/chat/completions", headers=h, json={
            "model": "muse",
            "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "mock reply"}
    assert body["choices"][0]["finish_reason"] == "stop"


def test_chat_stream_sse():
    c = TestClient(_app())
    h = {"Authorization": "Bearer test-key"}
    import muse2api.server as srv
    with patch.object(srv, "ChatSession", FakeChatSession), \
         patch.object(srv, "_ensure_gw", lambda acc: None):
        r = c.post("/v1/chat/completions", headers=h, json={
            "model": "muse", "stream": True,
            "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]
    chunks = [json.loads(ln[6:]) for ln in r.text.splitlines()
              if ln.startswith("data: ") and ln != "data: [DONE]"]
    assert r.text.strip().endswith("data: [DONE]")
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks)
    assert text == "mock reply"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_chat_requires_messages():
    c = TestClient(_app())
    h = {"Authorization": "Bearer test-key"}
    r = c.post("/v1/chat/completions", headers=h, json={"model": "muse"})
    assert r.status_code == 400
