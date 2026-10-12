"""POST /v1/chat/completions — streaming SSE and non-streaming."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...errors import Muse2APIError
from ..deps import require_api_key
from ..schemas import ChatCompletionRequest

router = APIRouter()


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk(
    chunk_id: str,
    model: str,
    created: int,
    *,
    delta: str | None = None,
    finish: str | None = None,
) -> dict[str, Any]:
    choice: dict[str, Any] = {"index": 0, "delta": {}, "finish_reason": finish}
    if delta is not None:
        choice["delta"]["content"] = delta
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [choice],
    }


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    _key: str = Depends(require_api_key),
):
    gateway = request.app.state.gateway
    settings = request.app.state.settings
    payload = body.model_dump(exclude_none=True)

    if not body.stream:
        data = await gateway.chat_complete(payload, settings.chat_timeout)
        return JSONResponse(data)

    stream_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    model = body.model

    async def gen():
        # Fetch the first delta before yielding anything: upstream errors
        # (auth, quota, ...) then surface as proper HTTP status codes
        # instead of a stream that breaks halfway.
        agen = gateway.chat_stream(payload, settings.chat_timeout)
        try:
            first = await asyncio.wait_for(
                agen.__anext__(), timeout=settings.upstream_timeout
            )
        except StopAsyncIteration:
            first = None
        if first is not None:
            yield _sse(_chunk(stream_id, model, created, delta=first))
        try:
            async for delta in agen:
                yield _sse(_chunk(stream_id, model, created, delta=delta))
        except Muse2APIError as e:
            # Mid-stream failure: OpenAI clients expect the error as an
            # SSE payload, then the stream ends.
            yield _sse(e.to_body())
            return
        yield _sse(_chunk(stream_id, model, created, finish="stop"))
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
