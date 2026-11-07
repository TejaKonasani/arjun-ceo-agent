"""Deployment gate tests — spec 16.6 tests 2, 6, 8 + lifecycle + rollback."""
from __future__ import annotations

from sutra import tools as T
from sutra.models import AgentStatus
from sutra.workflows import (
    human_approve,
    record_evaluation,
    request_deployment_approval,
    w01_register,
    w02_configure,
    w03_deploy,
    w04_rollback,
)


def _registered_agent(db, name="Pilot", canonical="SAM-AG-050"):
    reg = T.register_agent(
        db, name=name, canonical_id=canonical, position_id="TEC-050",
        department="Technology, MCP & AgentOps", role="Pilot agent",
        reports_to="SAM-AG-007", human_owner="Founder",
    )
    w01_register(db, reg["agent_id"])
    return reg


def _configured_agent(db, name="Pilot", canonical="SAM-AG-050"):
    reg = _registered_agent(db, name, canonical)
    w02_configure(db, reg["agent_id"], model="llama3.1:8b",
                  tools=["workflow"], permissions={"client_scopes": []})
    return reg


def test_deploy_without_approval_needs_approval(db):
    """16.6 #2: deploy without human approval → refuses, 'needs_approval'."""
    reg = _configured_agent(db)
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": True, "evidence": "run-1"},
    ])
    result = w03_deploy(db, reg["agent_id"])
    assert result["status"] == "needs_approval"
    assert result["approval_id"]
    # Not deployed.
    assert T.get_agent(db, reg["agent_id"]).status == AgentStatus.EVALUATED


def test_deploy_blocked_on_critical_test_failure(db):
    """13.3 #6: deploy an agent that failed a critical test → BLOCKED."""
    reg = _configured_agent(db)
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": False, "evidence": "run-2"},
    ])
    # Even WITH a (human) approval, a critical failure blocks deployment.
    appr = request_deployment_approval(db, reg["agent_id"])
    human_approve(db, appr["approval_id"], approver="Founder")
    result = w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])
    assert result["status"] == "blocked"
    assert result["failed_critical_tests"]


def test_deploy_idempotent(db):
    """16.6 #8: run the same deploy twice → second detects 'already deployed'."""
    reg = _configured_agent(db)
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": True, "evidence": "run-3"},
    ])
    appr = request_deployment_approval(db, reg["agent_id"])
    human_approve(db, appr["approval_id"], approver="Founder")

    first = w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])
    assert first["status"] == "deployed"

    second = w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])
    assert second["status"] == "already_deployed"


def test_full_lifecycle(db):
    """proposed → registered → configured → evaluated → approved → active/monitored."""
    reg = _configured_agent(db, name="FullCycle", canonical="SAM-AG-051")
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": True, "evidence": "run-4"},
        {"name": "quality", "critical": False, "passed": True, "evidence": "run-4"},
    ])
    appr = request_deployment_approval(db, reg["agent_id"])
    human_approve(db, appr["approval_id"], approver="Founder")
    result = w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])
    assert result["status"] == "deployed"
    assert result["lifecycle_status"] == AgentStatus.MONITORED
    assert T.get_agent(db, reg["agent_id"]).deployed_version


def test_rollback_requires_runbook(db):
    """Permission matrix: rollback only within approved emergency runbook."""
    reg = _configured_agent(db, name="RollMe", canonical="SAM-AG-052")
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": True, "evidence": "run-5"},
    ])
    appr = request_deployment_approval(db, reg["agent_id"])
    human_approve(db, appr["approval_id"], approver="Founder")
    w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])

    # Without runbook approval → needs approval.
    result = w04_rollback(db, reg["agent_id"], reason="bad version")
    assert result["status"] == "needs_approval"

    # With runbook approved → rolled back.
    result = w04_rollback(db, reg["agent_id"], reason="bad version",
                          runbook_approved=True)
    assert result["status"] == "rolled_back"


def test_suspend_blocks_gateway(db, gateway):
    """Suspended agent is immediately blocked from all tool calls."""
    reg = _configured_agent(db, name="SuspendMe", canonical="SAM-AG-053")
    agent = T.get_agent(db, reg["agent_id"])

    # Allowed while active-in-lifecycle (configured + granted 'workflow').
    result = gateway.execute(agent, "workflow", "create_task", {"title": "t1"})
    assert result["status"] == "ok"

    # Suspend → gateway denies.
    T.suspend_agent(db, reg["agent_id"], reason="emergency")
    from sutra.gateway import GatewayDenialError

    try:
        gateway.execute(agent, "workflow", "create_task", {"title": "t2"})
        assert False, "expected GatewayDenialError"
    except GatewayDenialError as exc:
        assert "suspended" in exc.reason