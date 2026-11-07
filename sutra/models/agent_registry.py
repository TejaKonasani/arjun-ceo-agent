"""`agents` table — the agent registry (Pehchaan's data model).

Every agent: canonical ID, position ID, name, department, reports-to,
permissions, lifecycle state, model version, prompt version, cost limits,
evaluation history (section 16.3).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus:
    """The 8 agent lifecycle states (PDF2 p.64)."""

    PROPOSED = "proposed"
    REGISTERED = "registered"
    CONFIGURED = "configured"
    EVALUATED = "evaluated"
    APPROVED = "approved"
    ACTIVE = "active"
    MONITORED = "monitored"
    UPDATED = "updated"
    RETIRED = "retired"

    ALL = [
        PROPOSED,
        REGISTERED,
        CONFIGURED,
        EVALUATED,
        APPROVED,
        ACTIVE,
        MONITORED,
        UPDATED,
        RETIRED,
    ]


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("canonical_id", name="uq_agents_canonical_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    position_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=AgentStatus.PROPOSED, index=True)

    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tools: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    reports_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evaluator: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Cost limits / governance
    cost_limit_tokens_per_day: Mapped[int | None] = mapped_column(nullable=True)

    # Evaluation evidence (Parikshak results, append-only summary)
    evaluation_history: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Deployment bookkeeping
    deployed_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suspended: Mapped[bool] = mapped_column(default=False)
    suspend_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "canonical_id": self.canonical_id,
            "name": self.name,
            "position_id": self.position_id,
            "department": self.department,
            "role": self.role,
            "status": self.status,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "tools": self.tools,
            "permissions": self.permissions,
            "reports_to": self.reports_to,
            "evaluator": self.evaluator,
            "human_owner": self.human_owner,
            "cost_limit_tokens_per_day": self.cost_limit_tokens_per_day,
            "evaluation_history": self.evaluation_history,
            "deployed_version": self.deployed_version,
            "suspended": self.suspended,
            "suspend_reason": self.suspend_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }