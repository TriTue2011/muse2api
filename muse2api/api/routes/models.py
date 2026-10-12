"""GET /v1/models and GET /v1/models/{model}"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...errors import NotFound
from ..deps import require_api_key

router = APIRouter()


@router.get("/v1/models")
async def list_models(
    request: Request, _key: str = Depends(require_api_key)
) -> dict:
    models = await request.app.state.gateway.list_models()
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": m.id,
                "object": "model",
                "created": m.created or now,
                "owned_by": m.owned_by,
            }
            for m in models
        ],
    }


@router.get("/v1/models/{model_id}")
async def get_model(
    model_id: str, request: Request, _key: str = Depends(require_api_key)
) -> dict:
    model = await request.app.state.gateway.get_model(model_id)
    if model is None:
        raise NotFound(f"model '{model_id}' not found")
    return {
        "id": model.id,
        "object": "model",
        "created": model.created or int(time.time()),
        "owned_by": model.owned_by,
    }
