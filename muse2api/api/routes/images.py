"""Image endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from ...errors import Unsupported
from ..deps import require_api_key
from ..schemas import ImageGenerationRequest

router = APIRouter()


@router.post("/v1/images/generations")
async def images_generations(
    body: ImageGenerationRequest,
    request: Request,
    _key: str = Depends(require_api_key),
):
    gateway = request.app.state.gateway
    settings = request.app.state.settings
    data = await gateway.generate_image(
        body.model_dump(exclude_none=True), settings.image_timeout
    )
    return JSONResponse(data)


@router.post("/v1/images/edits")
async def images_edits(request: Request, _key: str = Depends(require_api_key)):
    gateway = request.app.state.gateway
    settings = request.app.state.settings
    driver = gateway.driver
    if not driver.capabilities.image_edit:
        raise Unsupported(
            f"driver '{driver.name}' does not support image edits",
            alternative="use POST /v1/images/generations",
        )
    raw = await request.body()
    upstream = await driver.edit_image_passthrough(
        raw,
        request.headers.get("content-type", ""),
        settings.image_timeout,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
