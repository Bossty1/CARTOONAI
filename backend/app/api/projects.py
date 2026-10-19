"""Project CRUD and nested resource listings."""
from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from ..models import Asset, Job, Project, Video
from ..schemas import AssetRead, JobRead, ProjectCreate, ProjectRead, ProjectUpdate, VideoRead
from .deps import Auth, DbSession, Owner, get_project, serialize_asset, serialize_project

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Auth])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    session: DbSession,
    owner: Owner,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectRead]:
    projects = session.execute(
        select(Project).where(Project.owner == owner).order_by(Project.updated_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return [serialize_project(project) for project in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: DbSession, owner: Owner) -> ProjectRead:
    project = Project(name=payload.name, description=payload.description, status=payload.status, owner=owner)
    session.add(project)
    session.commit()
    session.refresh(project)
    return serialize_project(project)


@router.get("/{project_id}", response_model=ProjectRead)
def read_project(project_id: str, session: DbSession, owner: Owner) -> ProjectRead:
    return serialize_project(get_project(session, project_id, owner))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, session: DbSession, owner: Owner) -> ProjectRead:
    project = get_project(session, project_id, owner)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = payload.status
    session.commit()
    session.refresh(project)
    return serialize_project(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, session: DbSession, owner: Owner) -> None:
    project = get_project(session, project_id, owner)
    session.delete(project)
    session.commit()


@router.get("/{project_id}/assets", response_model=list[AssetRead])
def list_project_assets(project_id: str, session: DbSession, owner: Owner) -> list[AssetRead]:
    get_project(session, project_id, owner)
    assets = session.execute(
        select(Asset).where(Asset.project_id == project_id, Asset.owner == owner).order_by(Asset.created_at.desc())
    ).scalars()
    return [serialize_asset(asset) for asset in assets]


@router.get("/{project_id}/jobs", response_model=list[JobRead])
def list_project_jobs(project_id: str, session: DbSession, owner: Owner) -> list[JobRead]:
    get_project(session, project_id, owner)
    jobs = session.execute(
        select(Job).where(Job.project_id == project_id, Job.owner == owner).order_by(Job.created_at.desc())
    ).scalars()
    return [JobRead.model_validate(job) for job in jobs]


@router.get("/{project_id}/videos", response_model=list[VideoRead])
def list_project_videos(project_id: str, session: DbSession, owner: Owner) -> list[VideoRead]:
    get_project(session, project_id, owner)
    videos = session.execute(
        select(Video).where(Video.project_id == project_id, Video.owner == owner).order_by(Video.created_at.desc())
    ).scalars()
    result: list[VideoRead] = []
    for video in videos:
        payload = VideoRead.model_validate(video)
        if video.output_asset_id:
            payload.content_url = f"/api/assets/{video.output_asset_id}/content"
        result.append(payload)
    return result
