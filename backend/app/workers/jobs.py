"""In-process job runner with a swap-friendly queue interface."""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.errors import AppError, not_found
from ..db import get_session_factory
from ..models import Asset, Job, new_id

logger = logging.getLogger("cartoon_ai.jobs")

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_job(
    session: Session,
    job_type: str,
    owner: str,
    project_id: str | None,
    config: dict[str, Any],
) -> Job:
    job = Job(id=new_id(), type=job_type, owner=owner, project_id=project_id, config=config, status=STATUS_QUEUED)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


class JobContext:
    """Handle passed to job handlers: progress reporting and asset access."""

    def __init__(self, job: Job, session: Session, settings: Settings) -> None:
        self.id = job.id
        self.type = job.type
        self.owner = job.owner
        self.project_id = job.project_id
        self.config: dict[str, Any] = dict(job.config or {})
        self.session = session
        self.settings = settings
        self.result: dict[str, Any] = {}
        self._job = job
        self._log_lines: list[str] = []

    def update(self, progress: int | None = None, stage: str | None = None) -> None:
        if progress is not None:
            self._job.progress = max(0, min(100, int(progress)))
        if stage is not None:
            self._job.stage = stage
        if self._log_lines:
            self._job.logs = "\n".join(self._log_lines)
        self.session.commit()

    def log(self, message: str) -> None:
        stamp = _utcnow().strftime("%H:%M:%S")
        self._log_lines.append(f"[{stamp}] {message}")
        logger.info("job %s: %s", self.id, message)
        self._job.logs = "\n".join(self._log_lines)
        self.session.commit()

    def set_result(self, **values: Any) -> None:
        self.result.update(values)
        self._job.result = dict(self.result)
        self.session.commit()

    def fetch_asset(self, asset_id: str, allowed_kinds: tuple[str, ...] | None = None) -> Asset:
        asset = self.session.execute(
            select(Asset).where(Asset.id == asset_id, Asset.owner == self.owner)
        ).scalar_one_or_none()
        if asset is None:
            raise not_found("ASSET_NOT_FOUND", "That asset does not exist or is not available to you.")
        if allowed_kinds and asset.kind not in allowed_kinds:
            raise AppError(
                "ASSET_KIND_MISMATCH",
                f"Asset '{asset.id}' is a {asset.kind} but the job needs one of {list(allowed_kinds)}.",
                details={"asset_kind": asset.kind, "expected": list(allowed_kinds)},
            )
        return asset


Handler = Callable[[JobContext], None]


class JobRunner:
    """Thread-pool runner. Replace with a broker-backed queue in production."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self.settings.job_workers), thread_name_prefix="cartoon-job"
        )

    def enqueue(self, job_id: str, handler: Handler) -> None:
        self._executor.submit(self._execute, job_id, handler)

    def _execute(self, job_id: str, handler: Handler) -> None:
        session = get_session_factory()()
        try:
            job = session.get(Job, job_id)
            if job is None:
                logger.warning("job %s disappeared before execution", job_id)
                return
            job.status = STATUS_PROCESSING
            job.started_at = _utcnow()
            job.stage = "starting"
            job.progress = 1
            session.commit()
            context = JobContext(job, session, self.settings)
            try:
                handler(context)
            except AppError as exc:
                self._fail(job, exc.code, exc.message)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("job %s crashed", job_id)
                self._fail(job, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", traceback.format_exc())
            else:
                job.status = STATUS_COMPLETED
                job.stage = "completed"
                job.progress = 100
                job.result = dict(context.result)
                job.logs = "\n".join(context._log_lines)
                job.finished_at = _utcnow()
                session.commit()
        finally:
            session.close()

    @staticmethod
    def _fail(job: Job, code: str, message: str, detail: str | None = None) -> None:
        job.status = STATUS_FAILED
        job.stage = "failed"
        job.error_code = code
        job.error_message = message
        if detail:
            job.logs = f"{job.logs}\n{detail}".strip()
        job.finished_at = _utcnow()
        session = Session.object_session(job)
        if session is not None:
            session.commit()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


def reset_runner() -> None:
    global _runner
    if _runner is not None:
        _runner.shutdown()
    _runner = None


def run_job_sync(job_id: str, handler: Handler, settings: Settings | None = None) -> None:
    """Execute a queued job in the calling thread (used by tests)."""
    runner = JobRunner(settings=settings)
    try:
        runner._execute(job_id, handler)
    finally:
        runner.shutdown()
