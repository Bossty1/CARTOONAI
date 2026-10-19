"""Video creation and retrieval."""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from ..core.errors import not_found
from ..core.security import client_key, enforce_rate_limit
from ..models import Video, new_id
from ..schemas import JobRead, VideoCreateRequest, VideoRead
from ..services.ffmpeg_tools import ffmpeg_available, missing_ffmpeg_error
from ..workers import create_job, get_runner
from ..workers.tasks import run_video
from .deps import Auth, DbSession, Owner, get_asset, get_project

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Auth])


class VideoJobResponse(BaseModel):
    job: JobRead
    video: VideoRead
    ffmpeg_available: bool = True


def _serialize_video(video: Video) -> VideoRead:
    payload = VideoRead.model_validate(video)
    if video.output_asset_id:
        payload.content_url = f"/api/assets/{video.output_asset_id}/content"
    return payload


@router.post("", response_model=VideoJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_video(payload: VideoCreateRequest, request: Request, session: DbSession, owner: Owner) -> VideoJobResponse:
    enforce_rate_limit(f"video:{client_key(request, owner)}")
    if payload.project_id:
        get_project(session, payload.project_id, owner)
    for frame in payload.frames:
        get_asset(session, frame.asset_id, owner)
    if payload.audio and payload.audio.asset_id:
        get_asset(session, payload.audio.asset_id, owner)

    if not ffmpeg_available():
        raise missing_ffmpeg_error()

    video = Video(
        id=new_id(),
        project_id=payload.project_id,
        owner=owner,
        status="queued",
        fps=payload.fps,
    )
    session.add(video)
    session.commit()
    session.refresh(video)

    config = payload.model_dump(mode="json")
    config["video_id"] = video.id
    job = create_job(session, job_type="video", owner=owner, project_id=payload.project_id, config=config)
    job.result = {"video_id": video.id, "frame_count": len(payload.frames), "resolution": payload.resolution}
    session.commit()
    get_runner().enqueue(job.id, run_video)
    return VideoJobResponse(job=JobRead.model_validate(job), video=_serialize_video(video), ffmpeg_available=True)


@router.get("", response_model=list[VideoRead])
def list_videos(
    session: DbSession,
    owner: Owner,
    project_id: str | None = None,
) -> list[VideoRead]:
    query = select(Video).where(Video.owner == owner)
    if project_id:
        query = query.where(Video.project_id == project_id)
    videos = session.execute(query.order_by(Video.created_at.desc())).scalars()
    return [_serialize_video(video) for video in videos]


@router.get("/{video_id}", response_model=VideoRead)
def read_video(video_id: str, session: DbSession, owner: Owner) -> VideoRead:
    video = session.execute(select(Video).where(Video.id == video_id, Video.owner == owner)).scalar_one_or_none()
    if video is None:
        raise not_found("VIDEO_NOT_FOUND", "That video does not exist or is not available to you.")
    return _serialize_video(video)
