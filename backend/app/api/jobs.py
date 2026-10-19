"""Job status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..core.errors import not_found
from ..models import Job
from ..schemas import JobLogs, JobRead
from .deps import Auth, DbSession, Owner

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Auth])


@router.get("", response_model=list[JobRead])
def list_jobs(
    session: DbSession,
    owner: Owner,
    project_id: str | None = Query(default=None),
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JobRead]:
    query = select(Job).where(Job.owner == owner)
    if project_id:
        query = query.where(Job.project_id == project_id)
    if job_status:
        query = query.where(Job.status == job_status)
    jobs = session.execute(query.order_by(Job.created_at.desc()).limit(limit)).scalars()
    return [JobRead.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobRead)
def read_job(job_id: str, session: DbSession, owner: Owner) -> JobRead:
    job = session.execute(select(Job).where(Job.id == job_id, Job.owner == owner)).scalar_one_or_none()
    if job is None:
        raise not_found("JOB_NOT_FOUND", "That job does not exist or is not available to you.")
    return JobRead.model_validate(job)


@router.get("/{job_id}/logs", response_model=JobLogs)
def read_job_logs(job_id: str, session: DbSession, owner: Owner) -> JobLogs:
    job = session.execute(select(Job).where(Job.id == job_id, Job.owner == owner)).scalar_one_or_none()
    if job is None:
        raise not_found("JOB_NOT_FOUND", "That job does not exist or is not available to you.")
    return JobLogs(id=job.id, status=job.status, progress=job.progress, stage=job.stage, logs=job.logs or "")
