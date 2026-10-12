"""Liveness, readiness, and the honest support matrix."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ... import __version__
from ...errors import Unsupported

router = APIRouter()

SUPPORT_MATRIX = {
    "supported": [
        "GET /healthz",
        "GET /readyz",
        "GET /support",
        "GET /v1/status (no auth, mirrors upstream)",
        "GET /v1/models",
        "GET /v1/models/{model}",
        "POST /v1/chat/completions (streaming + non-streaming)",
        "POST /v1/responses (non-streaming)",
        "POST /v1/images/generations",
        "POST /v1/images/edits (transparent proxy, no schema assumptions)",
    ],
    "unsupported": {
        "/v1/videos*": {
            "reason": "Meta's official Model API documents no video-generation endpoint.",
            "alternative": "Generate video in the muse.ai web app, or put a "
            "dedicated video model behind this same gateway pattern.",
        },
        "muse.ai personal agent (threads, VM, connectors, memory)": {
            "reason": "Meta publishes no public API for the Muse agent app itself.",
            "alternative": "The Model API serves the same Muse Spark models; "
            "build agent features on top of /v1/chat/completions and /v1/responses.",
        },
        "POST /v1/responses with stream=true": {
            "reason": "Not implemented in this gateway yet.",
            "alternative": "Use stream=false, or POST /v1/chat/completions "
            "with stream=true.",
        },
        "/v1/messages* (Anthropic-compatible)": {
            "reason": "Documented officially, but not implemented in this gateway yet.",
            "alternative": "Use the OpenAI-compatible /v1/chat/completions or "
            "/v1/responses instead.",
        },
        "/v1/files*": {
            "reason": "Documented officially, but not implemented in this gateway yet.",
            "alternative": "Manage files directly against https://api.meta.ai/v1 "
            "with your API key.",
        },
        "/v1/asr/* (voice transcription)": {
            "reason": "Documented officially, but not implemented in this gateway yet.",
            "alternative": "Call POST /v1/asr/transcribe directly against "
            "https://api.meta.ai/v1 with your API key.",
        },
    },
}


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    return await request.app.state.gateway.driver.health()


@router.get("/support")
async def support() -> dict:
    return SUPPORT_MATRIX


@router.get("/v1/status")
async def service_status(request: Request):
    # Mirrors upstream GET /v1/status, which needs no authentication.
    data = await request.app.state.gateway.service_status()
    return JSONResponse(data)


@router.api_route("/v1/videos", methods=["GET", "POST"])
async def videos_unsupported() -> dict:
    raise Unsupported(
        "video generation is not part of Meta's official Model API",
        alternative=SUPPORT_MATRIX["unsupported"]["/v1/videos*"]["alternative"],
    )


@router.api_route("/v1/videos/{task_id}", methods=["GET", "POST"])
async def video_task_unsupported(task_id: str) -> dict:
    raise Unsupported(
        "video generation is not part of Meta's official Model API",
        alternative=SUPPORT_MATRIX["unsupported"]["/v1/videos*"]["alternative"],
    )
