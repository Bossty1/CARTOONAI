"""Cartoonization endpoint (queues a job and explains the engine that will run)."""
from __future__ import annotations

from fastapi import APIRouter, Request, status

from ..core.errors import AppError
from ..core.security import client_key, enforce_rate_limit
from ..schemas import CartoonizeRequest, JobRead
from ..services.cartoon import resolve_engine
from ..workers import create_job, get_runner
from ..workers.tasks import run_cartoonize
from .deps import Auth, DbSession, Owner, get_asset, get_project

router = APIRouter(tags=["cartoon"])


@router.post("/cartoonize", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED, dependencies=[Auth])
def cartoonize(payload: CartoonizeRequest, request: Request, session: DbSession, owner: Owner) -> JobRead:
    enforce_rate_limit(f"cartoonize:{client_key(request, owner)}")
    if payload.project_id:
        get_project(session, payload.project_id, owner)
    get_asset(session, payload.asset_id, owner)
    if payload.background == "remove":
        raise AppError(
            "BACKGROUND_REMOVAL_UNAVAILABLE",
            "Background removal needs a segmentation model, which is not configured.",
            status_code=status.HTTP_409_CONFLICT,
            details={"available_options": ["keep", "blur"], "docs": "cartoon-ai-studio/models/README.md"},
        )
    engine, meta = resolve_engine(payload.engine, payload.allow_classic_fallback)
    job = create_job(
        session,
        job_type="cartoonize",
        owner=owner,
        project_id=payload.project_id,
        config=payload.model_dump(mode="json"),
    )
    job.result = {"planned_engine": engine.info.engine, "planned_is_ai": engine.info.is_ai, "engine_note": meta.get("note")}
    session.commit()
    get_runner().enqueue(job.id, run_cartoonize)
    return JobRead.model_validate(job)
