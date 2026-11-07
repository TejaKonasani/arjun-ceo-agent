"""W04 — Rollback (within the approved emergency runbook).

Permission matrix: "Execute rollback — ⚠️ Within approved emergency
runbook — Escalation and post-review."
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..tools.deploy import rollback_agent
from ..tools.incident import close_incident, resolve_incident
from ..tools.registry import get_agent


def w04_rollback(db: Session, agent_ref: str, *, reason: str,
                 runbook_approved: bool = False,
                 incident_id: str | None = None) -> dict:
    """Roll back an agent, optionally closing the linked incident."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    result = rollback_agent(db, agent_ref, reason=reason, runbook_approved=runbook_approved)

    if result.get("status") == "rolled_back" and incident_id:
        result["incident_resolution"] = resolve_incident(
            db, incident_id,
            root_cause=reason,
            resolution=f"Rolled back {agent.canonical_id} to previous version",
        )
    return result