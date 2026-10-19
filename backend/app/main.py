"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import build_router
from .core.config import get_settings
from .core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .db import init_db
from .services.ffmpeg_tools import ffmpeg_available, ffmpeg_version
from .services.storage import get_storage
from .workers import reset_runner

logger = logging.getLogger("cartoon_ai")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    get_storage().ensure_ready()
    for area, path in settings.storage_areas.items():
        path.mkdir(parents=True, exist_ok=True)
    if ffmpeg_available(settings):
        logger.info("FFmpeg detected: %s", ffmpeg_version(settings))
    else:
        logger.warning(
            "FFmpeg was not found: image features work, video rendering returns FFMPEG_MISSING. "
            "Set FFMPEG_BINARY or install FFmpeg (docker-compose includes it)."
        )
    logger.info("Storage provider: %s", settings.storage_provider)
    yield
    reset_runner()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.version,
        description=(
            "Image-to-cartoon and cartoon-video studio. Cartoonization engines are reported honestly: "
            "engine='classic-filter' with is_ai=false is an OpenCV filter preset, not a neural network."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Owner-Id", "X-API-Key"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(build_router(), prefix=settings.api_prefix)

    @app.get("/", tags=["system"])
    def index() -> dict[str, object]:
        return {
            "app": f"{settings.app_name} API",
            "version": settings.version,
            "docs": "/docs",
            "api": settings.api_prefix,
            "endpoints": [
                f"{settings.api_prefix}/health",
                f"{settings.api_prefix}/capabilities",
                f"{settings.api_prefix}/uploads",
                f"{settings.api_prefix}/cartoonize",
                f"{settings.api_prefix}/images/adjust",
                f"{settings.api_prefix}/jobs/{{job_id}}",
                f"{settings.api_prefix}/videos",
                f"{settings.api_prefix}/assets/{{asset_id}}",
                f"{settings.api_prefix}/projects",
            ],
        }

    return app


app = create_app()
