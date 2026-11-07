"""W01 — Register (lifecycle: proposed → registered).

Sutra's gate at step 02 (spec section 8): "Pehchaan created the registry
record. Sutra checks it's complete."
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Agent, AgentStatus
from ..tools.registry import get_agent, update_agent

REQUIRED_FIELDS = ("canonical_id", "name", "role", "department", "reports_to", "human_owner")


def w01_register(db: Session, agent_ref: str) -> dict:
    """Verify the registry record is complete, then move proposed → registered."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}
    if agent.status != AgentStatus.PROPOSED:
        return {"status": "blocked", "error": f"Agent is '{agent.status}', expected 'proposed'."}

    missing = [f for f in REQUIRED_FIELDS if not getattr(agent, f)]
    if missing:
        return {
            "status": "incomplete",
            "agent_id": agent.id,
            "canonical_id": agent.canonical_id,
            "missing_fields": missing,
            "error": "Registry record incomplete — cannot register until all required fields are present.",
        }

    agent = update_agent(db, agent, status=AgentStatus.REGISTERED)
    return {
        "status": "registered",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "lifecycle_status": agent.status,
        "checked_fields": REQUIRED_FIELDS,
    }