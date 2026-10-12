"""POST /v1/responses — Meta's Responses API (non-streaming)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...errors import Unsupported
from ..deps import require_api_key
from ..schemas import ResponsesRequest

router = APIRouter()


@router.post("/v1/responses")
async def responses_create(
    body: ResponsesRequest,
    request: Request,
    _key: str = Depends(require_api_key),
):
    if body.stream:
        raise Unsupported(
            "streaming for /v1/responses is not implemented yet",
            alternative="use stream=false, or POST /v1/chat/completions "
            "with stream=true",
        )
    gateway = request.app.state.gateway
    settings = request.app.state.settings
    data = await gateway.responses_create(
        body.model_dump(exclude_none=True), settings.chat_timeout
    )
    return JSONResponse(data)
