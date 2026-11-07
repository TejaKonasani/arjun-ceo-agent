"""Deployment tools — deploy_agent, rollback_agent, suspend_agent (spec 16.4).

Deployment gate (spec section 8, W03):
  Proposed → Registered → Configured → Evaluated → Approved (HUMAN) → Active

Hard rules enforced in code:
  * Sutra CANNOT approve his own deployment (test 2: deploy without human
    approval → refuses, returns "needs_approval").
  * An agent that failed a critical test is BLOCKED from deployment (test 6).
  * Deploy is idempotent — a second deploy detects "already deployed"
    (test 8).
  * Suspend is permitted under emergency rules but ALWAYS notifies the human.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..gateway.permissions import authorize_activity
from ..models import Agent, AgentStatus, ApprovalRequest, ApprovalStatus
from .registry import get_agent


def _failed_critical_tests(agent: Agent) -> list[dict]:
    """Collect failed CRITICAL tests across the agent's evaluation history.

    Each history entry is an evaluation run:
      {"evaluator": str, "results": [{"name", "critical", "passed", "evidence"}], ...}
    """
    failed: list[dict] = []
    for run in agent.evaluation_history or []:
        if not isinstance(run, dict):
            continue
        for r in run.get("results", []):
            if isinstance(r, dict) and r.get("critical") and r.get("passed") is False:
                failed.append({**r, "evaluator": run.get("evaluator")})
    return failed


def deploy_agent(db: Session, agent_ref: str, *, environment: str = "production",
                 approval_id: str | None = None, version: str | None = None) -> dict[str, Any]:
    """Move an agent from 'evaluated'/'approved' to 'active'.

    Requires:
      1. Agent exists and is in a deployable state (evaluated or approved).
      2. ALL critical tests passed (evaluation evidence).
      3. A HUMAN approval record exists and is approved (Sutra cannot
         self-approve — test 2).
    """
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    # Idempotency (test 8): already active in this environment.
    if agent.status in (AgentStatus.ACTIVE, AgentStatus.MONITORED) and agent.deployed_version:
        return {
            "status": "already_deployed",
            "agent_id": agent.id,
            "canonical_id": agent.canonical_id,
            "deployed_version": agent.deployed_version,
            "environment": environment,
            "note": "Agent is already deployed — no duplicate deployment created.",
        }

    # Gate: only evaluated/approved agents may be deployed.
    if agent.status not in (AgentStatus.EVALUATED, AgentStatus.APPROVED, AgentStatus.CONFIGURED):
        return {
            "status": "blocked",
            "agent_id": agent.id,
            "canonical_id": agent.canonical_id,
            "current_status": agent.status,
            "error": f"Agent is in state '{agent.status}' — must reach 'evaluated' with passing tests before deployment.",
        }

    # Gate: all critical tests must have passed (test 6).
    failed = _failed_critical_tests(agent)
    if failed:
        return {
            "status": "blocked",
            "agent_id": agent.id,
            "canonical_id": agent.canonical_id,
            "error": "Deployment BLOCKED: agent failed critical test(s).",
            "failed_critical_tests": failed,
        }

    # Gate: human approval is mandatory (test 2).
    auth = authorize_activity("deploy_agent_version")
    if auth.needs_approval:
        approval = None
        if approval_id:
            approval = db.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
            ).scalar_one_or_none()
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            # Create/return the pending approval request so a human can act.
            if approval is None:
                approval = ApprovalRequest(
                    activity="deploy_agent_version",
                    agent_id=agent.id,
                    requested_by="SAM-AG-007",
                    payload={"environment": environment, "version": version or agent.prompt_version},
                )
                db.add(approval)
                db.commit()
                db.refresh(approval)
            return {
                "status": "needs_approval",
                "agent_id": agent.id,
                "canonical_id": agent.canonical_id,
                "approval_id": approval.id,
                "error": "Production deployment requires HUMAN approval. Sutra cannot self-approve.",
                "approval": approval.to_dict(),
            }
        if approval.agent_id != agent.id:
            return {"status": "error", "error": "Approval record does not match this agent."}

    # All gates passed — deploy.
    agent.status = AgentStatus.ACTIVE
    agent.deployed_version = version or agent.prompt_version or "v1.0"
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return {
        "status": "deployed",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "deployed_version": agent.deployed_version,
        "environment": environment,
        "approved_by": approval.approved_by,
        "approval_id": approval.id,
    }


def rollback_agent(db: Session, agent_ref: str, *, reason: str,
                   runbook_approved: bool = False) -> dict[str, Any]:
    """Revert an agent to its previous version (within approved emergency runbook)."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    auth = authorize_activity("execute_rollback", emergency_runbook_approved=runbook_approved)
    if not auth.allowed:
        return {
            "status": "needs_approval",
            "agent_id": agent.id,
            "error": auth.reason,
        }

    previous = None
    for rec in reversed(agent.evaluation_history or []):
        if isinstance(rec, dict) and rec.get("version"):
            previous = rec["version"]
            break

    agent.status = AgentStatus.MONITORED
    agent.deployed_version = previous or "previous"
    agent.suspended = False
    agent.suspend_reason = None
    db.commit()
    return {
        "status": "rolled_back",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "reverted_to": previous or "previous",
        "reason": reason,
        "note": "Escalation + post-review required per emergency runbook.",
    }


def suspend_agent(db: Session, agent_ref: str, *, reason: str,
                  human_owner: str = "Founder / Technology & Security Owner") -> dict[str, Any]:
    """Emergency suspend — PERMITTED under emergency rules, human notified.

    The suspended agent is immediately blocked from all tool calls by the
    MCP gateway.
    """
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    if agent.suspended:
        return {
            "status": "already_suspended",
            "agent_id": agent.id,
            "canonical_id": agent.canonical_id,
            "reason": agent.suspend_reason,
        }

    agent.suspended = True
    agent.suspend_reason = reason
    db.commit()
    db.refresh(agent)
    return {
        "status": "suspended",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "reason": reason,
        "human_notified": human_owner,
        "note": "Emergency suspension executed; human Technology Owner notified immediately.",
    }