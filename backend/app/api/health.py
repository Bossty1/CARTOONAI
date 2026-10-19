"""Health and capability endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..core.config import get_settings
from ..schemas import CapabilitiesResponse, HealthResponse, StyleInfo
from ..services.cartoon import active_engine_id, engine_catalog, onnx_available, style_catalog
from ..services.ffmpeg_tools import ffmpeg_available, ffmpeg_version
from ..services.storage import get_storage
from .deps import DbSession

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    settings = get_settings()
    database = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on the database
        database = f"error: {type(exc).__name__}"
    storage_ok = True
    try:
        get_storage().ensure_ready()
    except Exception:
        storage_ok = False
    ffmpeg_ready = ffmpeg_available()
    status = "ok" if database == "ok" and storage_ok else "degraded"
    return HealthResponse(
        status=status,
        version=settings.version,
        environment=settings.environment,
        database=database,
        storage_provider=settings.storage_provider,
        storage_ok=storage_ok,
        ffmpeg_available=ffmpeg_ready,
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    settings = get_settings()
    engines = engine_catalog()
    onnx_engine = next((engine for engine in engines if engine.id == "onnx"), None)
    return CapabilitiesResponse(
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        storage_provider=settings.storage_provider,
        ffmpeg_available=ffmpeg_available(),
        ffmpeg_version=ffmpeg_version(),
        cartoon_engines=[engine.id for engine in engines],
        active_engine=active_engine_id(),
        classic_fallback_enabled=settings.allow_classic_fallback,
        ai_model_configured=onnx_available(),
        ai_model_requirements=onnx_engine.requires if onnx_engine else "",
        styles=[StyleInfo.model_validate(style) for style in style_catalog()],
        limits={
            "max_image_upload_mb": settings.max_image_upload_mb,
            "max_audio_upload_mb": settings.max_audio_upload_mb,
            "max_image_pixels": settings.max_image_pixels,
            "min_image_side": settings.min_image_side,
            "max_image_side": settings.max_image_side,
            "max_video_frames": 60,
            "video_resolutions": ["480p", "720p", "1080p"],
            "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
            "rate_limit_per_minute": settings.rate_limit_per_minute,
        },
    )


@router.get("/styles", response_model=list[StyleInfo])
def styles() -> list[StyleInfo]:
    return [StyleInfo.model_validate(style) for style in style_catalog()]


@router.get("/engines")
def engines() -> list[dict[str, object]]:
    return [
        {
            "id": engine.id,
            "label": engine.label,
            "engine": engine.engine,
            "is_ai": engine.is_ai,
            "license": engine.license,
            "requires": engine.requires,
        }
        for engine in engine_catalog()
    ]
