"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CartoonStyle = Literal["anime", "comic", "3d", "sketch", "illustration", "ink", "pastel"]
FrameEffect = Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]
TransitionType = Literal["none", "fade", "wipeleft", "wiperight", "slideup", "slidedown", "circle"]
AspectRatio = Literal["16:9", "9:16", "1:1", "4:3", "3:4"]
Resolution = Literal["480p", "720p", "1080p"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    status: Literal["draft", "active", "archived"] = "draft"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active", "archived"] | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    status: str
    owner: str
    created_at: datetime
    updated_at: datetime


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    provider: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    is_public: bool
    extra: dict[str, Any]
    created_at: datetime
    content_url: str | None = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    type: str
    status: str
    progress: int
    stage: str
    config: dict[str, Any]
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobLogs(BaseModel):
    id: str
    status: str
    progress: int
    stage: str
    logs: str


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    job_id: str | None
    output_asset_id: str | None
    status: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: int | None
    created_at: datetime
    content_url: str | None = None


class UploadResponse(BaseModel):
    asset: AssetRead
    content_url: str
    is_image: bool
    details: dict[str, Any] = Field(default_factory=dict)


class CropSettings(BaseModel):
    aspect_ratio: AspectRatio | None = None
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)


class AdjustmentSettings(BaseModel):
    brightness: float = Field(default=1.0, ge=0.1, le=3.0)
    contrast: float = Field(default=1.0, ge=0.1, le=3.0)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)
    sharpness: float = Field(default=0.0, ge=0.0, le=5.0)
    denoise: float = Field(default=0.0, ge=0.0, le=1.0)
    enhance: bool = False
    crop: CropSettings | None = None
    width: int | None = Field(default=None, ge=32, le=8000)
    height: int | None = Field(default=None, ge=32, le=8000)
    output_format: Literal["jpeg", "png", "webp"] = "jpeg"
    quality: int = Field(default=92, ge=50, le=100)


class CartoonizeRequest(BaseModel):
    asset_id: str
    project_id: str | None = None
    style: CartoonStyle = "anime"
    engine: Literal["auto", "classic", "onnx"] = "auto"
    strength: float = Field(default=0.85, ge=0.1, le=1.0)
    edge_strength: float = Field(default=0.6, ge=0.0, le=1.0)
    color_levels: int = Field(default=8, ge=2, le=32)
    smooth_iterations: int = Field(default=2, ge=1, le=6)
    output_format: Literal["jpeg", "png", "webp"] = "jpeg"
    quality: int = Field(default=92, ge=50, le=100)
    allow_classic_fallback: bool = True
    background: Literal["keep", "blur", "remove"] = "keep"
    save_asset: bool = True


class AdjustRequest(BaseModel):
    asset_id: str
    project_id: str | None = None
    adjustments: AdjustmentSettings = Field(default_factory=AdjustmentSettings)
    save_asset: bool = True


class FrameSpec(BaseModel):
    asset_id: str
    duration_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    effect: FrameEffect = "zoom_in"


class TransitionSpec(BaseModel):
    type: TransitionType = "fade"
    duration_seconds: float = Field(default=0.6, ge=0.1, le=3.0)


class AudioSpec(BaseModel):
    asset_id: str | None = None
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fade_in_seconds: float = Field(default=0.0, ge=0.0, le=10.0)
    fade_out_seconds: float = Field(default=0.0, ge=0.0, le=10.0)
    loop: bool = True


class VideoCreateRequest(BaseModel):
    project_id: str | None = None
    frames: list[FrameSpec] = Field(min_length=1, max_length=60)
    transition: TransitionSpec = Field(default_factory=TransitionSpec)
    aspect_ratio: AspectRatio = "16:9"
    resolution: Resolution = "720p"
    fps: int = Field(default=24, ge=6, le=60)
    audio: AudioSpec | None = None
    title: str = Field(default="cartoon-video", max_length=120)

    @field_validator("frames")
    @classmethod
    def _unique_frames(cls, value: list[FrameSpec]) -> list[FrameSpec]:
        ids = [frame.asset_id for frame in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Each frame must reference a different asset.")
        return value


class StyleInfo(BaseModel):
    id: str
    label: str
    description: str
    engine: str
    is_ai: bool


class CapabilitiesResponse(BaseModel):
    app_name: str
    version: str
    environment: str
    storage_provider: str
    ffmpeg_available: bool
    ffmpeg_version: str | None
    cartoon_engines: list[str]
    active_engine: str | None
    classic_fallback_enabled: bool
    ai_model_configured: bool
    ai_model_requirements: str
    styles: list[StyleInfo]
    limits: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    database: str
    storage_provider: str
    storage_ok: bool
    ffmpeg_available: bool


class ShareResponse(BaseModel):
    asset_id: str
    url: str | None
    expires_at: datetime | None
    provider: str
    shareable: bool
    message: str
