"""Queued tasks for the Sutra platform (run via Celery or eagerly)."""
from .celery_app import run_tec_p39, run_tec_p40

__all__ = ["run_tec_p39", "run_tec_p40"]