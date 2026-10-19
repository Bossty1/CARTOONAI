"""API routers."""
from fastapi import APIRouter

from . import assets, cartoon, health, images, jobs, projects, uploads, videos


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(projects.router)
    router.include_router(uploads.router)
    router.include_router(cartoon.router)
    router.include_router(images.router)
    router.include_router(jobs.router)
    router.include_router(videos.router)
    router.include_router(assets.router)
    router.include_router(assets.content_router)
    return router


__all__ = ["build_router"]
