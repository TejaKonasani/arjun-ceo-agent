"""Monitoring tools — get_agent_health, get_system_metrics (spec 16.4).

Test scenario 6: when data is missing, report "unavailable" for the missing
parts — never fabricate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Agent, AgentStatus, ExecutionLog, Incident, IncidentStatus
from .registry import get_agent, list_agents


def get_agent_health(db: Session, agent_ref: str) -> dict[str, Any]:
    """Health report for one agent. Missing data is reported as 'unavailable'."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    runs = db.execute(
        select(ExecutionLog).where(ExecutionLog.agent_id == agent.id,
                                   ExecutionLog.started_at >= since)
    ).scalars().all()
    total = len(runs)
    failed = sum(1 for r in runs if r.status == "failed")
    tokens = sum(r.tokens_used or 0 for r in runs)
    open_incidents = db.execute(
        select(Incident).where(Incident.agent_id == agent.id,
                               Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.CONTAINED]))
    ).scalars().all()

    return {
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "name": agent.name,
        "status": agent.status,
        "suspended": agent.suspended,
        "deployed_version": agent.deployed_version or "unavailable",
        "last_24h": {
            "executions": total,
            "failed": failed,
            "success_rate": round((total - failed) / total * 100, 2) if total else "unavailable",
            "tokens_used": tokens,
        },
        "open_incidents": [i.to_dict() for i in open_incidents],
        "evaluation_evidence": (
            "current" if (agent.evaluation_history or []) else "unavailable"
        ),
    }


def get_system_metrics(db: Session, gateway=None, *, window_hours: int = 24) -> dict[str, Any]:
    """Platform-wide metrics for Sutra's dashboard.

    Every metric that cannot be computed from real data is reported as
    'unavailable' — never invented (test scenario 6).
    """
    agents = list_agents(db)
    by_status: dict[str, int] = {}
    for a in agents:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    runs = db.execute(select(ExecutionLog).where(ExecutionLog.started_at >= since)).scalars().all()
    total_runs = len(runs)
    failed_runs = sum(1 for r in runs if r.status == "failed")
    partial_runs = sum(1 for r in runs if r.status == "partial")
    tokens = sum(r.tokens_used or 0 for r in runs)

    open_incidents = db.execute(
        select(Incident).where(Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.CONTAINED]))
    ).scalars().all()
    critical_open = [i for i in open_incidents if i.severity == "critical"]

    unauthorised = len(gateway.unauthorised_attempts()) if gateway else "unavailable"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "digital_workforce": {
            "registered": len(agents),
            "active": by_status.get(AgentStatus.ACTIVE, 0) + by_status.get(AgentStatus.MONITORED, 0),
            "restricted": sum(1 for a in agents if a.suspended),
            "retired": by_status.get(AgentStatus.RETIRED, 0),
            "by_status": by_status,
        },
        "workflow_execution": {
            "total": total_runs,
            "completed": total_runs - failed_runs - partial_runs,
            "failed": failed_runs,
            "retried": "unavailable",  # retry telemetry not yet wired (Nirikshak)
            "success_rate": round((total_runs - failed_runs) / total_runs * 100, 2) if total_runs else "unavailable",
        },
        "mcp_integrations": {
            "connected": "unavailable",  # connector health comes from Jod
            "degraded": "unavailable",
            "failed": "unavailable",
            "note": "Connector health telemetry not yet wired — reported as unavailable, not invented.",
        },
        "security": {
            "unauthorised_actions": unauthorised,
            "open_incidents": len(open_incidents),
            "critical_open": len(critical_open),
            "policy_violations": len(gateway.unauthorised_attempts()) if gateway else "unavailable",
        },
        "platform_reliability": {
            "availability": "unavailable",  # needs uptime probes (Nirikshak)
            "latency_p95_ms": _p95_latency(runs),
            "error_rate": round(failed_runs / total_runs * 100, 2) if total_runs else "unavailable",
        },
        "ai_execution_economics": {
            "tokens_used": tokens,
            "tool_costs": "unavailable",  # no paid APIs in this build
            "cost_per_task": "unavailable",
        },
        "versions_releases": {
            "deployed": sum(1 for a in agents if a.deployed_version),
            "testing": by_status.get(AgentStatus.EVALUATED, 0),
            "approved": by_status.get(AgentStatus.APPROVED, 0),
            "rolled_back": "unavailable",
        },
    }


def reconcile_telemetry(readings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reconcile multiple telemetry sources for the same metric (cert test 8).

    `readings`: {metric_name: {source_name: value}}. If two sources report
    different values for the same metric, the conflict is FLAGGED — Sutra
    never silently picks one source.
    """
    reconciled: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for metric, by_source in readings.items():
        values = {src: val for src, val in by_source.items() if val is not None}
        if not values:
            reconciled[metric] = {"value": "unavailable", "conflict": False,
                                  "sources": {}}
            continue
        distinct = {repr(v) for v in values.values()}
        if len(distinct) > 1:
            reconciled[metric] = {"value": "conflict", "conflict": True,
                                  "sources": values,
                                  "note": "Telemetry sources conflict — flagged, not silently resolved."}
            conflicts.append({"metric": metric, "sources": values})
        else:
            reconciled[metric] = {"value": next(iter(values.values())),
                                  "conflict": False, "sources": values}
    return {"reconciled": reconciled, "conflicts": conflicts,
            "conflict_count": len(conflicts)}


def _p95_latency(runs: list[ExecutionLog]) -> float | str:
    latencies = []
    for r in runs:
        if r.started_at and r.ended_at:
            latencies.append((r.ended_at - r.started_at).total_seconds() * 1000)
    if not latencies:
        return "unavailable"
    latencies.sort()
    idx = max(0, int(len(latencies) * 0.95) - 1)
    return round(latencies[idx], 2)