"""Celery application (task queue — spec 16.1: Celery + Redis, local).

Long-running platform jobs (monthly TEC-P39 review, telemetry aggregation,
roadmap refresh) are queued here. In the zero-setup local/sandbox mode the
same functions can be run eagerly (CELERY_TASK_ALWAYS_EAGER=1) without a
running Redis broker.
"""
from __future__ import annotations

import os

from celery import Celery

BROKER = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "sutra",
    broker=BROKER,
    backend=BACKEND,
    include=["sutra.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    # Eager mode lets the platform run the queue in-process when Redis is
    # not available (sandbox / tests).
    task_always_eager=os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1",
)


@celery_app.task(name="sutra.tec_p39_monthly_review")
def run_tec_p39() -> dict:
    """Monthly technology performance review (TEC-P39)."""
    from .database import SessionLocal, init_db
    from .gateway import MCPGateway
    from .workflows import tec_p39_monthly_review

    init_db()
    with SessionLocal() as db:
        gateway = MCPGateway(SessionLocal)
        from .gateway import register_default_handlers
        register_default_handlers(gateway)
        return tec_p39_monthly_review(db, gateway)


@celery_app.task(name="sutra.tec_p40_roadmap_update")
def run_tec_p40(items: list | None = None, board_priorities: list | None = None) -> dict:
    """Platform improvement roadmap update (TEC-P40)."""
    from .database import SessionLocal, init_db
    from .workflows import tec_p40_roadmap_update

    init_db()
    with SessionLocal() as db:
        return tec_p40_roadmap_update(db, items=items, board_priorities=board_priorities)