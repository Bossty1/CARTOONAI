"""Asset management plus the content-streaming endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from ..core.config import get_settings
from ..core.errors import AppError, not_found
from ..core.security import create_share_token, is_publicly_reachable, verify_share_token
from ..models import Asset
from ..schemas import AssetRead, ShareResponse
from ..services import image_service
from ..services.storage import get_storage
from .deps import Auth, DbSession, Owner, get_asset, serialize_asset

router = APIRouter(prefix="/assets", tags=["assets"], dependencies=[Auth])
content_router = APIRouter(prefix="/assets", tags=["assets"])

IMAGE_KINDS = ("image_original", "image_processed")


@router.get("", response_model=list[AssetRead])
def list_assets(
    session: DbSession,
    owner: Owner,
    project_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AssetRead]:
    query = select(Asset).where(Asset.owner == owner)
    if project_id:
        query = query.where(Asset.project_id == project_id)
    if kind:
        query = query.where(Asset.kind == kind)
    assets = session.execute(query.order_by(Asset.created_at.desc()).limit(limit)).scalars()
    return [serialize_asset(asset) for asset in assets]


@router.get("/{asset_id}", response_model=AssetRead)
def read_asset(asset_id: str, session: DbSession, owner: Owner) -> AssetRead:
    return serialize_asset(get_asset(session, asset_id, owner))


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str, session: DbSession, owner: Owner) -> None:
    asset = get_asset(session, asset_id, owner)
    storage = get_storage()
    try:
        storage.delete(asset.storage_key)
    except AppError:
        pass
    session.delete(asset)
    session.commit()


@router.post("/{asset_id}/share", response_model=ShareResponse)
def share_asset(asset_id: str, session: DbSession, owner: Owner) -> ShareResponse:
    settings = get_settings()
    asset = get_asset(session, asset_id, owner)
    storage = get_storage()
    ttl_seconds = settings.share_link_ttl_hours * 3600
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    if storage.supports_signed_urls and storage.name != "local":
        url = storage.signed_url(asset.storage_key, ttl_seconds)
        if url:
            asset.is_public = True
            session.commit()
            return ShareResponse(
                asset_id=asset.id,
                url=url,
                expires_at=expires_at,
                provider=storage.name,
                shareable=True,
                message=f"Signed {storage.name} URL, valid for {settings.share_link_ttl_hours} hours.",
            )
        return ShareResponse(
            asset_id=asset.id,
            url=None,
            expires_at=None,
            provider=storage.name,
            shareable=False,
            message=f"{storage.name} did not return a signed URL. Check the bucket permissions and credentials.",
        )

    if is_publicly_reachable(settings.public_base_url):
        token, expires_ts = create_share_token(asset.id, ttl_seconds)
        asset.is_public = True
        session.commit()
        base = settings.public_base_url.rstrip("/")
        url = f"{base}{settings.api_prefix}/assets/{asset.id}/content?token={token}"
        return ShareResponse(
            asset_id=asset.id,
            url=url,
            expires_at=datetime.fromtimestamp(expires_ts, tz=timezone.utc),
            provider="local",
            shareable=True,
            message=(
                "Local storage streams through this API, so the link works only while this server is "
                f"reachable at {base}. It expires in {settings.share_link_ttl_hours} hours."
            ),
        )

    return ShareResponse(
        asset_id=asset.id,
        url=None,
        expires_at=None,
        provider="local",
        shareable=False,
        message=(
            "PUBLIC_BASE_URL points at localhost, so no shareable link was created. Set it to a reachable "
            "address, or configure S3/GCS for signed URLs."
        ),
    )


def _may_read(asset: Asset, owner_header: str | None, token: str | None) -> bool:
    settings = get_settings()
    if verify_share_token(asset.id, token):
        return True
    if asset.is_public and token is None:
        return False
    if owner_header and owner_header == asset.owner:
        return True
    if not settings.require_auth and owner_header is None and asset.owner == settings.default_owner:
        return True
    return False


@content_router.get("/{asset_id}/content")
def asset_content(
    asset_id: str,
    session: DbSession,
    variant: str = Query(default="original"),
    download: bool = Query(default=False),
    token: str | None = Query(default=None),
    x_owner_id: str | None = Header(default=None),
):
    settings = get_settings()
    asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
    if asset is None:
        raise not_found("ASSET_NOT_FOUND", "That asset does not exist.")
    if not _may_read(asset, x_owner_id, token):
        raise AppError("ASSET_FORBIDDEN", "You do not have access to this asset.", status.HTTP_403_FORBIDDEN)

    storage = get_storage()
    filename = asset.filename or f"{asset.id}"
    headers = {"Cache-Control": "private, max-age=60" if not asset.is_public else "public, max-age=300"}

    if variant == "preview" and asset.kind in IMAGE_KINDS:
        with storage.open(asset.storage_key) as handle:
            preview = image_service.make_preview(handle.read())
        return Response(content=preview, media_type="image/jpeg", headers=headers)

    local_path = storage.local_path(asset.storage_key)
    disposition = "attachment" if download else "inline"
    is_attachment = download
    if local_path is not None:
        return FileResponse(
            local_path,
            media_type=asset.mime_type,
            filename=filename if is_attachment else None,
            content_disposition_type=disposition,
            headers=headers,
        )
    return StreamingResponse(
        storage.open(asset.storage_key),
        media_type=asset.mime_type,
        headers={**headers, "Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
