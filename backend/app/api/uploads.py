"""Uploads: images and audio files."""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile, status

from ..core.config import get_settings
from ..core.errors import AppError, payload_too_large
from ..core.security import client_key, enforce_rate_limit
from ..models import Asset
from ..schemas import UploadResponse
from ..services import image_service
from ..services.ffmpeg_tools import probe_media
from ..services.storage import get_storage
from .deps import Auth, DbSession, Owner, get_project, serialize_asset

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Auth])

AUDIO_TYPES: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
}
CHUNK_SIZE = 1024 * 1024


def _read_limited(upload: UploadFile, limit: int, label: str) -> bytes:
    buffer = bytearray()
    while True:
        chunk = upload.file.read(CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise payload_too_large(
                "UPLOAD_TOO_LARGE",
                f"The {label} exceeds the {limit // (1024 * 1024)} MB limit.",
                {"limit_bytes": limit},
            )
    if not buffer:
        raise AppError("EMPTY_UPLOAD", "The uploaded file is empty.")
    return bytes(buffer)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_file(
    request: Request,
    session: DbSession,
    owner: Owner,
    file: UploadFile = File(...),
    kind: str = Form(default="image"),
    project_id: str | None = Form(default=None),
) -> UploadResponse:
    settings = get_settings()
    kind = (kind or "image").lower()
    if kind not in {"image", "audio"}:
        raise AppError("UNSUPPORTED_UPLOAD_KIND", "kind must be 'image' or 'audio'.", details={"kind": kind})
    enforce_rate_limit(f"upload:{client_key(request, owner)}")

    if project_id:
        get_project(session, project_id, owner)

    if kind == "image":
        data = _read_limited(file, settings.max_image_upload_bytes, "image")
        info = image_service.sniff_image_info(data, settings)
        storage = get_storage()
        key = f"{project_id or 'unassigned'}/{uuid.uuid4().hex}.{info.extension}"
        stored = storage.save("uploads", key, data, info.mime_type)
        asset = Asset(
            project_id=project_id,
            owner=owner,
            kind="image_original",
            filename=Path(file.filename or f"upload.{info.extension}").name[:255],
            mime_type=info.mime_type,
            size_bytes=stored.size_bytes,
            provider=stored.provider,
            storage_key=stored.key,
            width=info.width,
            height=info.height,
            extra={"original_format": info.pil_format, "mode": info.mode},
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return UploadResponse(
            asset=serialize_asset(asset),
            content_url=f"{settings.api_prefix}/assets/{asset.id}/content",
            is_image=True,
            details={
                "width": info.width,
                "height": info.height,
                "preview_url": f"{settings.api_prefix}/assets/{asset.id}/content?variant=preview",
            },
        )

    data = _read_limited(file, settings.max_audio_upload_bytes, "audio file")
    content_type = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "").lower()
    extension = AUDIO_TYPES.get(content_type)
    if extension is None:
        guessed = Path(file.filename or "").suffix.lower().lstrip(".")
        if guessed in set(AUDIO_TYPES.values()):
            extension, content_type = guessed, f"audio/{guessed}"
        else:
            raise AppError(
                "UNSUPPORTED_AUDIO_TYPE",
                "Only MP3, WAV, M4A/AAC, OGG or WebM audio files are supported.",
                details={"received": content_type or "unknown", "allowed": sorted(AUDIO_TYPES)},
            )

    storage = get_storage()
    key = f"{project_id or 'unassigned'}/{uuid.uuid4().hex}.{extension}"
    stored = storage.save("uploads", key, data, content_type)
    asset = Asset(
        project_id=project_id,
        owner=owner,
        kind="audio",
        filename=Path(file.filename or f"audio.{extension}").name[:255],
        mime_type=content_type,
        size_bytes=stored.size_bytes,
        provider=stored.provider,
        storage_key=stored.key,
        extra={"validated": "declared content type accepted; FFmpeg validates the stream during rendering"},
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    details: dict[str, object] = {"note": "Audio is validated by FFmpeg when the video is rendered."}
    local_path = storage.local_path(stored.key)
    if local_path is not None:
        metadata = probe_media(local_path, settings)
        if metadata and metadata.get("format", {}).get("duration"):
            duration = float(metadata["format"]["duration"])
            asset.duration_seconds = duration
            session.commit()
            details["duration_seconds"] = duration
    return UploadResponse(
        asset=serialize_asset(asset),
        content_url=f"{settings.api_prefix}/assets/{asset.id}/content",
        is_image=False,
        details=details,
    )
