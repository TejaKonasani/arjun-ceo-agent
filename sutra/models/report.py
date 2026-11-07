"""`report` table — append-only reports with evidence links.

Sutra's monthly performance reports, incident reports, and roadmap
snapshots are persisted here. Append-only: rows are never mutated or
deleted (Sutra cannot erase negative feedback or evaluation history).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    __tablename__ = "report"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(64))  # e.g. monthly_tech_performance, incident, roadmap
    title: Mapped[str] = mapped_column(String(256))
    period: Mapped[str | None] = mapped_column(String(128), nullable=True)
    body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    routed_to: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "period": self.period,
            "body": self.body,
            "evidence": self.evidence,
            "routed_to": self.routed_to,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }