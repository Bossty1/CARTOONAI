"""Image adjustment endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request, status

from ..core.security import client_key, enforce_rate_limit
from ..schemas import AdjustRequest, JobRead
from ..workers import create_job, get_runner
from ..workers.tasks import run_adjust
from .deps import Auth, DbSession, Owner, get_asset, get_project

router = APIRouter(prefix="/images", tags=["images"], dependencies=[Auth])


@router.post("/adjust", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def adjust_image(payload: AdjustRequest, request: Request, session: DbSession, owner: Owner) -> JobRead:
    enforce_rate_limit(f"adjust:{client_key(request, owner)}")
    if payload.project_id:
        get_project(session, payload.project_id, owner)
    get_asset(session, payload.asset_id, owner)
    job = create_job(
        session,
        job_type="adjust",
        owner=owner,
        project_id=payload.project_id,
        config=payload.model_dump(mode="json"),
    )
    get_runner().enqueue(job.id, run_adjust)
    return JobRead.model_validate(job)
