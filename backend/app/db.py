"""Database engine and session management (SQLite locally, PostgreSQL-ready)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.resolved_database_url
        if url.startswith("sqlite:///"):
            db_file = Path(url.removeprefix("sqlite:///"))
            db_file.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        if url.startswith("sqlite"):
            _apply_sqlite_pragmas(_engine)
    return _engine


def _apply_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from . import models  # noqa: F401  (import registers the mappings)

    Base.metadata.create_all(bind=get_engine())


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
