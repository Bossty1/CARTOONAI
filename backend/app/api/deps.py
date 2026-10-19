"""Shared FastAPI dependencies and serialization helpers."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.errors import not_found
from ..core.security import current_owner, require_api_key
from ..db import get_db
from ..models import Asset, Project
from ..schemas import AssetRead, ProjectRead

DbSession = Annotated[Session, Depends(get_db)]
Owner = Annotated[str, Depends(current_owner)]
Auth = Depends(require_api_key)


def serialize_asset(asset: Asset) -> AssetRead:
    settings = get_settings()
    payload = AssetRead.model_validate(asset)
    payload.content_url = f"{settings.api_prefix}/assets/{asset.id}/content"
    return payload


def serialize_project(project: Project) -> ProjectRead:
    return ProjectRead.model_validate(project)


def get_project(session: Session, project_id: str, owner: str) -> Project:
    project = session.execute(
        select(Project).where(Project.id == project_id, Project.owner == owner)
    ).scalar_one_or_none()
    if project is None:
        raise not_found("PROJECT_NOT_FOUND", "That project does not exist or is not available to you.")
    return project


def get_asset(session: Session, asset_id: str, owner: str, *, allow_public: bool = False) -> Asset:
    conditions = [Asset.id == asset_id]
    if not allow_public:
        conditions.append(Asset.owner == owner)
    asset = session.execute(select(Asset).where(*conditions)).scalar_one_or_none()
    if asset is None:
        raise not_found("ASSET_NOT_FOUND", "That asset does not exist or is not available to you.")
    return asset
