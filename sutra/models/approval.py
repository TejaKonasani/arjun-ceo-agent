"""`approval_request` table — the human approval gate.

Hard rule: Sutra cannot approve his own changes or certify his own work.
Every material change (deploy, privileged tool, production credential,
security policy change, data deletion, backup restore) must be routed
here and approved by a HUMAN before it executes.
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


class ApprovalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"

    ALL = [PENDING, APPROVED, REJECTED, EXPIRED]


class ApprovalRequest(Base):
    __tablename__ = "approval_request"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    activity: Mapped[str] = mapped_column(String(64))  # e.g. deploy_agent, grant_privileged_tool
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="SAM-AG-007")  # Sutra
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "activity": self.activity,
            "agent_id": self.agent_id,
            "requested_by": self.requested_by,
            "payload": self.payload,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }