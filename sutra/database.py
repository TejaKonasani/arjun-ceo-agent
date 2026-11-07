"""Database engine + session management.

The spec's fixed stack is PostgreSQL (local). The engine is driven by the
`DATABASE_URL` environment variable so the same code runs against:

  * PostgreSQL (production, per the spec):
        DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/sutra
  * SQLite (default — zero-setup local run / sandbox):
        DATABASE_URL=sqlite:///./sutra_platform.db

All tables are defined with SQLAlchemy so the schema is identical on both.
"""
from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///./sutra_platform.db"


class Base(DeclarativeBase):
    pass


def _resolve_url() -> tuple[str, dict]:
    url = os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DB_URL
    if url.startswith("sqlite") and ":memory:" in url:
        # Shared in-memory database (used by the test suite).
        return url, {"poolclass": StaticPool}
    return url, {}


_url, _kwargs = _resolve_url()
connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine = create_engine(_url, connect_args=connect_args, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    from . import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)