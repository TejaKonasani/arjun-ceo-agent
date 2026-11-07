"""Agent registry tools — register_agent, get_agent, update_agent (spec 16.4).

`register_agent` creates a record with status "proposed" (test scenario 1:
"Creates record with status 'proposed', returns agent_id").
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, AgentStatus


def register_agent(
    db: Session,
    *,
    name: str,
    role: str | None = None,
    department: str | None = None,
    position_id: str | None = None,
    canonical_id: str | None = None,
    tools: list[str] | None = None,
    permissions: dict[str, Any] | None = None,
    reports_to: str | None = None,
    evaluator: str | None = None,
    human_owner: str | None = None,
    model: str | None = "llama3.1:8b",
    prompt_version: str | None = "v1.0",
) -> dict[str, Any]:
    """Create a new agent in the registry with status 'proposed'.

    Registering a draft agent is PERMITTED for Sutra (permission matrix),
    but activation requires review — the agent cannot call tools until it
    reaches at least 'registered'.
    """
    from sqlalchemy.exc import IntegrityError

    agent = Agent(
        name=name,
        canonical_id=canonical_id or _next_canonical_id(db),
        position_id=position_id,
        department=department,
        role=role,
        status=AgentStatus.PROPOSED,
        model=model,
        prompt_version=prompt_version,
        tools={"namespaces": tools or []},
        permissions=permissions or {},
        reports_to=reports_to,
        evaluator=evaluator,
        human_owner=human_owner,
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "error", "error": f"canonical_id already exists: {agent.canonical_id}"}
    db.refresh(agent)
    return {
        "status": "registered_draft",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "lifecycle_status": agent.status,
        "note": "Draft agent created. Activation requires review before it may call tools.",
    }


def _next_canonical_id(db: Session) -> str:
    existing = db.execute(select(Agent.canonical_id)).scalars().all()
    nums = []
    for cid in existing:
        if cid and cid.startswith("SAM-AG-"):
            try:
                nums.append(int(cid.split("-")[-1]))
            except ValueError:
                pass
    return f"SAM-AG-{(max(nums) + 1) if nums else 1:03d}"


def get_agent(db: Session, agent_ref: str) -> Agent | None:
    """Fetch an agent by UUID or canonical_id."""
    stmt = select(Agent).where((Agent.id == agent_ref) | (Agent.canonical_id == agent_ref))
    return db.execute(stmt).scalar_one_or_none()


def list_agents(db: Session, status: str | None = None) -> list[Agent]:
    stmt = select(Agent).order_by(Agent.canonical_id)
    if status:
        stmt = stmt.where(Agent.status == status)
    return list(db.execute(stmt).scalars().all())


def update_agent(db: Session, agent: Agent, **fields: Any) -> Agent:
    """Update mutable fields on an agent record (system-level write)."""
    for key, value in fields.items():
        if hasattr(agent, key):
            setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent_ref: str) -> dict[str, Any]:
    """DELETE is NOT independently permitted for Sutra (permission matrix).

    Test scenario 4: "Ask Sutra to delete an agent → Refuses. Offers
    'suspend' instead." This function always refuses and points to suspend.
    """
    return {
        "status": "refused",
        "error": "Deleting an agent is not independently permitted — human approval required.",
        "suggestion": "Use suspend_agent instead (permitted under emergency rules, human notified).",
        "needs_approval": True,
    }