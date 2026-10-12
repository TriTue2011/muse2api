"""FastAPI server: OpenAI-compatible API over the muse.ai direct protocol.

Endpoints:
  GET  /v1/models
  POST /v1/chat/completions   (stream and non-stream)
  GET  /health                (no auth)

The upstream protocol client is blocking, so every upstream call runs in a
worker thread; concurrent API requests on the same account are serialized
by the account lock (the upstream chat history is shared per account).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from typing import AsyncIterator

import anyio
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .accounts import Account, Pool
from .config import Settings
from .upstream.chat import ChatSession, build_prompt
from .upstream.protocol import AuthError, GatewayError

log = logging.getLogger("muse2api.server")


def _http_error(e: Exception) -> HTTPException:
    if isinstance(e, AuthError):
        return HTTPException(status_code=401, detail={
            "error": {"message": f"muse.ai auth failed: {e} "
                                 "(cookies expired? re-export from your browser)",
                      "type": "authentication_error", "code": "invalid_cookies"}})
    if isinstance(e, TimeoutError):
        return HTTPException(status_code=504, detail={
            "error": {"message": str(e), "type": "timeout_error"}})
    if isinstance(e, GatewayError):
        return HTTPException(status_code=502, detail={
            "error": {"message": f"muse.ai gateway error: {e}",
                      "type": "upstream_error"}})
    return HTTPException(status_code=500, detail={
        "error": {"message": f"{type(e).__name__}: {e}", "type": "server_error"}})


def _ensure_gw(account: Account) -> None:
    """Connect (once), retrying a single time on failure. Raises on error."""
    try:
        account.ensure()
    except Exception as e1:  # noqa: BLE001 - reconnect once
        account.drop(f"ensure failed: {e1}")
        account.ensure()  # raises if still broken


def _run_session(account: Account, settings: Settings, prompt: str):
    """Build a ChatSession on a live connection (blocking)."""
    _ensure_gw(account)
    return ChatSession(account._gw, account.node_id,
                       poll_interval=settings.poll_interval,
                       wait_s=settings.wait_s, quiet_s=settings.quiet_s)


def create_app(settings: Settings, pool: Pool) -> FastAPI:
    app = FastAPI(title="muse2api",
                  description="OpenAI-compatible API for muse.ai (direct protocol, cookie auth)")

    def check_auth(authorization: str | None):
        if settings.api_key and authorization != f"Bearer {settings.api_key}":
            raise HTTPException(status_code=401, detail={
                "error": {"message": "invalid API key", "type": "authentication_error"}})

    @app.get("/health")
    async def health():
        return {"ok": any(a["healthy"] for a in pool.status()),
                "accounts": pool.status()}

    @app.get("/v1/models")
    async def models(authorization: str | None = Header(default=None)):
        check_auth(authorization)
        return {"object": "list", "data": [{
            "id": settings.model_name, "object": "model",
            "created": int(time.time()), "owned_by": "muse2api"}]}

    def _do_chat(account: Account, prompt: str) -> str:
        """Blocking full-turn chat. No retry after send (avoid duplicates)."""
        sess = _run_session(account, settings, prompt)
        try:
            return sess.run_collect(prompt)
        except AuthError as e:
            account.mark_auth_failed(str(e))
            raise
        except Exception as e:  # noqa: BLE001
            account.drop(f"chat failed: {type(e).__name__}: {e}")
            raise

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request,
                               authorization: str | None = Header(default=None)):
        check_auth(authorization)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={
                "error": {"message": "invalid JSON body", "type": "invalid_request_error"}})
        messages = body.get("messages") or []
        if not isinstance(messages, list) or not messages:
            raise HTTPException(status_code=400, detail={
                "error": {"message": "'messages' must be a non-empty array",
                          "type": "invalid_request_error"}})
        prompt = build_prompt(messages)
        if not prompt.strip():
            raise HTTPException(status_code=400, detail={
                "error": {"message": "empty prompt", "type": "invalid_request_error"}})
        model = body.get("model") or settings.model_name
        stream = bool(body.get("stream"))
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        if stream:
            return StreamingResponse(
                _stream_chat(settings, pool, prompt, model, chat_id, created),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        account = pool.acquire()
        try:
            try:
                text = await anyio.to_thread.run_sync(_do_chat, account, prompt)
            except Exception as e:  # noqa: BLE001
                raise _http_error(e)
        finally:
            pool.release(account)
        return JSONResponse({
            "id": chat_id, "object": "chat.completion", "created": created,
            "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

    return app


async def _stream_chat(settings: Settings, pool: Pool, prompt: str,
                       model: str, chat_id: str, created: int) -> AsyncIterator[str]:
    """SSE stream. Account is connected BEFORE streaming starts so auth and
    connection errors surface as HTTP errors, not broken streams."""
    account = pool.acquire()
    try:
        try:
            await anyio.to_thread.run_sync(_ensure_gw, account)
        except Exception as e:  # noqa: BLE001
            if isinstance(e, AuthError):
                account.mark_auth_failed(str(e))
            else:
                account.drop(f"ensure failed: {e}")
            raise _http_error(e)
        q: queue.Queue = queue.Queue()

        def _worker():
            try:
                sess = ChatSession(account._gw, account.node_id,
                                   poll_interval=settings.poll_interval,
                                   wait_s=settings.wait_s, quiet_s=settings.quiet_s)
                for delta in sess.run(prompt):
                    q.put(("delta", delta))
                q.put(("done", None))
            except AuthError as e:
                account.mark_auth_failed(str(e))
                q.put(("error", e))
            except Exception as e:  # noqa: BLE001
                account.drop(f"chat failed: {type(e).__name__}: {e}")
                q.put(("error", e))
            finally:
                pool.release(account)

        threading.Thread(target=_worker, daemon=True).start()
        first = True
        while True:
            kind, payload = await anyio.to_thread.run_sync(q.get)
            if kind == "delta":
                delta = {"role": "assistant", "content": payload} if first else \
                    {"content": payload}
                first = False
                chunk = {"id": chat_id, "object": "chat.completion.chunk",
                         "created": created, "model": model,
                         "choices": [{"index": 0, "delta": delta,
                                      "finish_reason": None}]}
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif kind == "done":
                chunk = {"id": chat_id, "object": "chat.completion.chunk",
                         "created": created, "model": model,
                         "choices": [{"index": 0, "delta": {},
                                      "finish_reason": "stop"}]}
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return
            else:  # error mid-stream: end the stream with an error payload
                err = _http_error(payload)
                detail = err.detail if isinstance(err.detail, dict) else {"error": str(payload)}
                yield f"data: {json.dumps(detail, ensure_ascii=False)}\n\n"
                return
    except HTTPException:
        pool.release(account)
        raise
