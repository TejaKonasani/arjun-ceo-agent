"""W03 — Deploy gate (Sutra's most important daily workflow, spec section 8).

Agent lifecycle (PDF2 p.64):
  01 Proposed → 02 Registered → 03 Configured → 04 Evaluated
  → 05 Approved (HUMAN) → 06 Active → 07 Monitored → 08 Updated/Retired

Sutra's gate at each step is enforced here. The critical rule: step 05
(Approved) is a HUMAN sign-off — Sutra routes the request but CANNOT
approve it himself.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Agent, AgentStatus, ApprovalRequest, ApprovalStatus
from ..tools.deploy import deploy_agent
from ..tools.registry import get_agent, update_agent


def record_evaluation(db: Session, agent_ref: str, *, results: list[dict[str, Any]],
                      evaluator: str = "SAM-AG-014") -> dict:
    """Parikshak (test lab) records the test suite results (step 04).

    `results`: list of {"name": str, "critical": bool, "passed": bool, "evidence": str}
    Moves configured → evaluated only when the suite ran; a failed CRITICAL
    test blocks deployment downstream (test scenario 6).
    """
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}
    if agent.status != AgentStatus.CONFIGURED:
        return {"status": "blocked", "error": f"Agent is '{agent.status}', expected 'configured'."}

    history = list(agent.evaluation_history or [])
    history.append({
        "evaluator": evaluator,
        "results": results,
        "all_critical_passed": all(r.get("passed") for r in results if r.get("critical")),
    })
    agent = update_agent(db, agent, status=AgentStatus.EVALUATED,
                         evaluation_history=history, evaluator=evaluator)
    critical_failed = [r["name"] for r in results if r.get("critical") and not r.get("passed")]
    return {
        "status": "evaluated",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "lifecycle_status": agent.status,
        "critical_tests_failed": critical_failed,
    }


def request_deployment_approval(db: Session, agent_ref: str, *, environment: str = "production",
                                note: str = "") -> dict:
    """Step 05: route the deployment for HUMAN sign-off (Sutra cannot self-approve)."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}
    if agent.status not in (AgentStatus.EVALUATED, AgentStatus.APPROVED):
        return {"status": "blocked", "error": f"Agent is '{agent.status}' — must be evaluated first."}

    req = ApprovalRequest(
        activity="deploy_agent_version",
        agent_id=agent.id,
        requested_by="SAM-AG-007",
        payload={"environment": environment, "note": note},
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {
        "status": "routed_for_approval",
        "approval_id": req.id,
        "agent": agent.canonical_id,
        "note": "HUMAN sign-off required. Sutra cannot approve this step himself.",
    }


def human_approve(db: Session, approval_id: str, *, approver: str) -> dict:
    """The HUMAN approves (or rejects) a deployment request.

    Hard rule: Sutra cannot self-approve. An approver that is an agent
    canonical ID (e.g. SAM-AG-007) is refused — only a human identity may
    approve.
    """
    if approver and (approver.startswith("SAM-AG-") or approver.lower() in ("sutra",)):
        return {
            "status": "refused",
            "error": "Self-approval is not permitted. A HUMAN must approve this request.",
        }
    req = db.get(ApprovalRequest, approval_id)
    if req is None:
        return {"status": "error", "error": f"Approval request not found: {approval_id}"}
    if req.status != ApprovalStatus.PENDING:
        return {"status": "blocked", "error": f"Request already {req.status}."}
    req.status = ApprovalStatus.APPROVED
    req.approved_by = approver
    from datetime import datetime, timezone
    req.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "approved", "approval_id": approval_id, "approved_by": approver}


def w03_deploy(db: Session, agent_ref: str, *, environment: str = "production",
               approval_id: str | None = None) -> dict:
    """Full deployment gate: verify state + tests + human approval, then deploy."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    result = deploy_agent(db, agent_ref, environment=environment, approval_id=approval_id)

    # After a successful deploy, the agent is monitored (step 07).
    if result.get("status") == "deployed":
        agent = get_agent(db, agent_ref)
        if agent and agent.status == AgentStatus.ACTIVE:
            update_agent(db, agent, status=AgentStatus.MONITORED)
            result["lifecycle_status"] = AgentStatus.MONITORED
            result["note"] = "Deployed and under monitoring (Nirikshak telemetry + Chaukidar watch)."
    return result