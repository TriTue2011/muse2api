"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .api.routes import chat, images, models, responses, system
from .config import Settings
from .drivers.base import MuseDriver
from .errors import InvalidRequest, Muse2APIError
from .services.gateway import Gateway, build_driver

log = logging.getLogger("muse2api")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # Quieten chatty libraries; our own loggers stay at the chosen level.
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_app(
    settings: Settings | None = None, driver: MuseDriver | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    _setup_logging(settings.log_level)
    driver = driver or build_driver(settings)
    gateway = Gateway(driver)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info(
            "starting muse2api %s (driver=%s) on %s:%d",
            __version__,
            driver.name,
            settings.host,
            settings.port,
        )
        await driver.startup()
        yield
        await driver.shutdown()
        log.info("muse2api stopped")

    app = FastAPI(title="muse2api", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.gateway = gateway

    @app.exception_handler(Muse2APIError)
    async def _muse2api_error(request: Request, exc: Muse2APIError):
        log.warning("%s %s -> %s: %s", request.method, request.url.path,
                    exc.status_code, exc.message)
        return JSONResponse(exc.to_body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        err = InvalidRequest(f"request validation failed: {exc.errors()}")
        return JSONResponse(err.to_body(), status_code=err.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        err = Muse2APIError("internal server error")
        return JSONResponse(err.to_body(), status_code=500)

    for router in (system.router, models.router, chat.router,
                   responses.router, images.router):
        app.include_router(router)

    return app
