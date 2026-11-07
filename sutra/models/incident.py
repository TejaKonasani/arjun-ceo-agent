"""`incident` table — critical technical incidents (spec 16.3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IncidentSeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    ALL = [LOW, MEDIUM, HIGH, CRITICAL]


class IncidentStatus:
    OPEN = "open"
    CONTAINED = "contained"
    RESOLVED = "resolved"
    CLOSED = "closed"

    ALL = [OPEN, CONTAINED, RESOLVED, CLOSED]


class Incident(Base):
    __tablename__ = "incident"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default=IncidentSeverity.LOW, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=IncidentStatus.OPEN, index=True)
    escalated_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[list | None] = mapped_column(Text, nullable=True)  # JSON list of events
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        import json

        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "severity": self.severity,
            "description": self.description,
            "status": self.status,
            "escalated_to": self.escalated_to,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "timeline": json.loads(self.timeline) if self.timeline else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }