"""Test configuration — fresh in-memory database per test.

Sets DATABASE_URL to a shared in-memory SQLite BEFORE importing sutra so
the whole platform (models, tools, agent) runs against it.
"""
from __future__ import annotations

import os

# Must be set before sutra.database is imported.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("OLLAMA_BASE_URL", None)

import pytest  # noqa: E402

from sutra.database import Base, SessionLocal, engine  # noqa: E402
from sutra.gateway import MCPGateway, register_default_handlers  # noqa: E402


@pytest.fixture()
def db():
    """A clean database session for each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def gateway(db):
    g = MCPGateway(SessionLocal)
    register_default_handlers(g)
    return g


@pytest.fixture()
def sutra_agent(db, gateway):
    """Sutra agent with an Ollama client pointed at a dead port
    (model unavailable → deterministic mode, no fake output)."""
    from sutra.agents import OllamaClient, SutraAgent

    llm = OllamaClient(endpoint="http://127.0.0.1:59999", model="llama3.1:8b")
    return SutraAgent(gateway, llm)