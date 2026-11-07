"""Incident tools — log_incident, escalate_incident (spec 16.4 + W04).

Workflow SUTRA-W04 — Critical Incident Response:
  1. Confirm severity
  2. Contain (suspend failing agent/workflow)
  3. Notify the human Technology Owner immediately (MANDATORY for critical)
  4. Coordinate the fix
  5. Rollback if the bad version caused it
  6. Track to closure with corrective evidence
  7. Record the full timeline (audit trail)
  8. Feed lessons into the roadmap (W02)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Incident, IncidentSeverity, IncidentStatus
from .registry import get_agent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def log_incident(db: Session, *, agent_ref: str | None = None, severity: str,
                 description: str) -> dict[str, Any]:
    """Record an incident. Critical incidents are auto-escalated to the human."""
    if severity not in IncidentSeverity.ALL:
        return {"status": "error", "error": f"Invalid severity '{severity}'. Use one of {IncidentSeverity.ALL}"}

    agent = get_agent(db, agent_ref) if agent_ref else None
    incident = Incident(
        agent_id=agent.id if agent else None,
        severity=severity,
        description=description,
        status=IncidentStatus.OPEN,
        timeline=json.dumps([{"at": _now().isoformat(), "event": "incident logged"}]),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    result: dict[str, Any] = {
        "status": "logged",
        "incident_id": incident.id,
        "severity": severity,
        "agent": agent.canonical_id if agent else None,
    }

    # Critical → immediate escalation (mandatory).
    if severity == IncidentSeverity.CRITICAL:
        esc = escalate_incident(db, incident.id, human_owner="Founder / Technology & Security Owner")
        result["escalated"] = esc
    return result


def escalate_incident(db: Session, incident_id: str, *,
                      human_owner: str = "Founder / Technology & Security Owner") -> dict[str, Any]:
    """Escalate an incident to the human Technology Owner (mandatory for critical)."""
    incident = db.execute(select(Incident).where(Incident.id == incident_id)).scalar_one_or_none()
    if incident is None:
        return {"status": "error", "error": f"Incident not found: {incident_id}"}

    if incident.escalated_to is None:
        incident.escalated_to = human_owner
        incident.escalated_at = _now()
        timeline = json.loads(incident.timeline or "[]")
        timeline.append({"at": _now().isoformat(), "event": f"escalated to {human_owner}"})
        incident.timeline = json.dumps(timeline)
        db.commit()
        db.refresh(incident)
        return {
            "status": "escalated",
            "incident_id": incident.id,
            "escalated_to": human_owner,
            "note": "Human Technology Owner notified immediately.",
        }
    return {
        "status": "already_escalated",
        "incident_id": incident.id,
        "escalated_to": incident.escalated_to,
    }


def get_incident_log(db: Session, include_closed: bool = True) -> list[dict[str, Any]]:
    """Open and closed incidents with status."""
    stmt = select(Incident).order_by(Incident.created_at.desc())
    if not include_closed:
        stmt = stmt.where(Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.CONTAINED]))
    return [i.to_dict() for i in db.execute(stmt).scalars().all()]


def contain_incident(db: Session, incident_id: str, *, agent_ref: str | None = None,
                     reason: str = "incident containment") -> dict[str, Any]:
    """Step 2 of W04: suspend the failing agent (containment)."""
    from .deploy import suspend_agent

    if not agent_ref:
        return {"status": "error", "error": "containment requires an agent_ref to suspend"}
    result = suspend_agent(db, agent_ref, reason=f"{reason} (incident {incident_id})")
    # Record containment on the incident.
    incident = db.execute(select(Incident).where(Incident.id == incident_id)).scalar_one_or_none()
    if incident:
        incident.status = IncidentStatus.CONTAINED
        timeline = json.loads(incident.timeline or "[]")
        timeline.append({"at": _now().isoformat(), "event": f"containment: {result.get('status')}"})
        incident.timeline = json.dumps(timeline)
        db.commit()
    return result


def resolve_incident(db: Session, incident_id: str, *, root_cause: str,
                     resolution: str, corrective_evidence: bool = True) -> dict[str, Any]:
    """Steps 5-6 of W04: closure only after corrective evidence is verified."""
    incident = db.execute(select(Incident).where(Incident.id == incident_id)).scalar_one_or_none()
    if incident is None:
        return {"status": "error", "error": f"Incident not found: {incident_id}"}
    if not corrective_evidence:
        return {
            "status": "blocked",
            "error": "Closure requires verified corrective evidence (W04 step 6).",
        }
    incident.status = IncidentStatus.RESOLVED
    incident.root_cause = root_cause
    incident.resolution = resolution
    incident.resolved_at = _now()
    timeline = json.loads(incident.timeline or "[]")
    timeline.append({"at": _now().isoformat(), "event": "resolved with corrective evidence"})
    incident.timeline = json.dumps(timeline)
    db.commit()
    return {"status": "resolved", "incident_id": incident_id, "root_cause": root_cause}


def close_incident(db: Session, incident_id: str) -> dict[str, Any]:
    """Final closure after resolution is verified."""
    incident = db.execute(select(Incident).where(Incident.id == incident_id)).scalar_one_or_none()
    if incident is None:
        return {"status": "error", "error": f"Incident not found: {incident_id}"}
    if incident.status != IncidentStatus.RESOLVED:
        return {"status": "blocked", "error": "Incident must be resolved before closure."}
    incident.status = IncidentStatus.CLOSED
    timeline = json.loads(incident.timeline or "[]")
    timeline.append({"at": _now().isoformat(), "event": "closed"})
    incident.timeline = json.dumps(timeline)
    db.commit()
    return {"status": "closed", "incident_id": incident_id}