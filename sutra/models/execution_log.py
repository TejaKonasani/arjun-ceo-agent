"""`execution_log` table — structured execution record for every agent run.

Covers the 13.1 fields: execution ID, agent ID + version, workflow/task,
timestamps, model & tools, input/output, tokens, failure classification,
approval record, final status.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionStatus:
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    ESCALATED = "escalated"


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[str | None] = mapped_column(Text, nullable=True)

    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=ExecutionStatus.SUCCESS, index=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "client_id": self.client_id,
            "task": self.task,
            "input": self.input,
            "output": self.output,
            "model_used": self.model_used,
            "tools_used": self.tools_used,
            "status": self.status,
            "failure_class": self.failure_class,
            "approval_record": self.approval_record,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "tokens_used": self.tokens_used,
            "error": self.error,
        }