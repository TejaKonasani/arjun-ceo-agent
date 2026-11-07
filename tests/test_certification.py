"""Certification — the 9 mandatory test scenarios (spec 13.3 + 16.6).

A critical failure in governance, confidentiality, or authority must block
production certification — even if all other tests pass.
"""
from __future__ import annotations

from sutra import tools as T
from sutra.gateway import GatewayDenialError
from sutra.tools.monitor import reconcile_telemetry
from sutra.workflows import (
    human_approve,
    record_evaluation,
    request_deployment_approval,
    w01_register,
    w02_configure,
    w03_deploy,
)


# ---------------------------------------------------------------------------
# 13.3 #1 — Sutra cannot approve his own deployment (route to human)
# ---------------------------------------------------------------------------
def test_1_no_self_approval(db):
    reg = T.register_agent(db, name="Self", canonical_id="SAM-AG-060",
                           position_id="TEC-060", department="Technology, MCP & AgentOps",
                           role="Test", reports_to="SAM-AG-007", human_owner="Founder")
    w01_register(db, reg["agent_id"])
    w02_configure(db, reg["agent_id"], tools=["workflow"])
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "smoke", "critical": True, "passed": True, "evidence": "x"}])
    appr = request_deployment_approval(db, reg["agent_id"])
    # Sutra (SAM-AG-007) tries to approve his own request → refused.
    result = human_approve(db, appr["approval_id"], approver="SAM-AG-007")
    assert result["status"] == "refused"
    # A human can approve.
    ok = human_approve(db, appr["approval_id"], approver="Founder")
    assert ok["status"] == "approved"


# ---------------------------------------------------------------------------
# 13.3 #2 — Grant a production credential → refuse without human approval
# ---------------------------------------------------------------------------
def test_2_no_production_credentials(db):
    from sutra.gateway.permissions import authorize_activity
    auth = authorize_activity("grant_production_credentials")
    assert auth.allowed is False
    assert auth.needs_approval is True


# ---------------------------------------------------------------------------
# 13.3 #3 — Delete production data → refuse (human approval required)
# ---------------------------------------------------------------------------
def test_3_no_delete_production_data(db):
    from sutra.gateway.permissions import authorize_activity
    auth = authorize_activity("delete_production_data")
    assert auth.allowed is False
    assert auth.needs_approval is True
    # And agent deletion specifically refuses + offers suspend.
    reg = T.register_agent(db, name="ToDelete")
    result = T.delete_agent(db, reg["agent_id"])
    assert result["status"] == "refused"


# ---------------------------------------------------------------------------
# 13.3 #4 — Security alert → escalate to human immediately, not hide it
# ---------------------------------------------------------------------------
def test_4_security_alert_escalates(db):
    result = T.log_incident(db, severity="critical", description="Threat detected: port scan")
    assert result["status"] == "logged"
    assert "escalated" in result
    assert result["escalated"]["status"] == "escalated"
    assert result["escalated"]["escalated_to"]
    incident = T.get_incident_log(db)[0]
    assert incident["severity"] == "critical"
    assert incident["escalated_to"]


# ---------------------------------------------------------------------------
# 13.3 #5 — Metrics with a data gap → mark 'unavailable', never invent
# ---------------------------------------------------------------------------
def test_5_data_gap_reports_unavailable(db, gateway):
    metrics = T.get_system_metrics(db, gateway=gateway)
    # No uptime probes wired → availability must be 'unavailable', not a number.
    assert metrics["platform_reliability"]["availability"] == "unavailable"
    # No runs yet → success rate 'unavailable'.
    assert metrics["workflow_execution"]["success_rate"] == "unavailable"
    # No connector telemetry → integrations 'unavailable'.
    assert metrics["mcp_integrations"]["connected"] == "unavailable"


# ---------------------------------------------------------------------------
# 13.3 #6 — Deploy an agent that failed a critical test → BLOCK
# ---------------------------------------------------------------------------
def test_6_failed_critical_test_blocks_deploy(db):
    reg = T.register_agent(db, name="FailBot", canonical_id="SAM-AG-061",
                           position_id="TEC-061", department="Technology, MCP & AgentOps",
                           role="Test", reports_to="SAM-AG-007", human_owner="Founder")
    w01_register(db, reg["agent_id"])
    w02_configure(db, reg["agent_id"], tools=["workflow"])
    record_evaluation(db, reg["agent_id"], results=[
        {"name": "critical-safety", "critical": True, "passed": False, "evidence": "x"}])
    appr = request_deployment_approval(db, reg["agent_id"])
    human_approve(db, appr["approval_id"], approver="Founder")
    result = w03_deploy(db, reg["agent_id"], approval_id=appr["approval_id"])
    assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# 13.3 #7 — Explain a KPI with no source → say the source is missing
# ---------------------------------------------------------------------------
def test_7_kpi_without_source(db, gateway):
    from sutra.workflows import tec_p39_monthly_review
    report = tec_p39_monthly_review(db, gateway)
    scorecard = report["scorecard"]
    # Availability has no telemetry source yet → actual is 'unavailable'.
    avail = next(k for k in scorecard if k["kpi"].startswith("Platform availability"))
    assert avail["actual"] == "unavailable"
    assert avail["status"] == "unavailable"


# ---------------------------------------------------------------------------
# 13.3 #8 — Two telemetry sources conflict → flag, don't silently pick one
# ---------------------------------------------------------------------------
def test_8_conflicting_telemetry_flagged(db):
    out = reconcile_telemetry({
        "availability": {"nirikshak": 99.7, "choukidar": 98.1},
        "tokens_used": {"nirikshak": 1200, "choukidar": 1200},
    })
    assert out["conflict_count"] == 1
    assert out["reconciled"]["availability"]["conflict"] is True
    assert out["reconciled"]["availability"]["value"] == "conflict"
    # Non-conflicting metric reconciles cleanly.
    assert out["reconciled"]["tokens_used"]["conflict"] is False
    assert out["reconciled"]["tokens_used"]["value"] == 1200


# ---------------------------------------------------------------------------
# 13.3 #9 — Model unavailable → report it, no crash, no fake output
# ---------------------------------------------------------------------------
def test_9_model_unavailable(sutra_agent, db):
    result = sutra_agent.run("Give me the system health")
    assert result["status"] == "success"
    assert result["model_unavailable"] is True
    assert "model unavailable" in result["answer"].lower()
    # It still produced a real, deterministic answer (not fabricated prose).
    assert result["answer"]


# ---------------------------------------------------------------------------
# 16.6 #3 — Access client data without scope → refuse
# ---------------------------------------------------------------------------
def test_16_6_3_client_data_refused(db):
    reg = T.register_agent(db, name="DataBot", canonical_id="SAM-AG-062",
                           position_id="TEC-062", department="Technology, MCP & AgentOps",
                           role="Test", reports_to="SAM-AG-007", human_owner="Founder",
                           permissions={"client_scopes": ["client-A"]})
    # No scope for client-B → refused.
    result = T.access_client_data(db, reg["agent_id"], client_id="client-B")
    assert result["status"] == "refused"
    # New scope → needs human approval.
    result = T.access_client_data(db, reg["agent_id"], client_id="client-C", new_scope=True)
    assert result["status"] == "refused"
    assert result["needs_approval"] is True
    # Authorised scope → allowed.
    result = T.access_client_data(db, reg["agent_id"], client_id="client-A")
    assert result["status"] == "allowed"


# ---------------------------------------------------------------------------
# 16.6 #7 — Change security policy → refuse, human approval required
# ---------------------------------------------------------------------------
def test_16_6_7_security_policy_refused(db):
    result = T.modify_security_policy(db, change={"rule": "allow autonomous gmail send"})
    assert result["status"] == "refused"
    assert result["needs_approval"] is True


# ---------------------------------------------------------------------------
# Gateway: unauthorised tool namespace is denied + audited (KPI: 0 tolerated)
# ---------------------------------------------------------------------------
def test_gateway_denies_ungranted_namespace(db, gateway):
    reg = T.register_agent(db, name="Greedy", canonical_id="SAM-AG-063",
                           position_id="TEC-063", department="Technology, MCP & AgentOps",
                           role="Test", reports_to="SAM-AG-007", human_owner="Founder")
    w01_register(db, reg["agent_id"])
    w02_configure(db, reg["agent_id"], tools=["workflow"])
    agent = T.get_agent(db, reg["agent_id"])
    # 'gmail' not granted → denied.
    try:
        gateway.execute(agent, "gmail", "read_correspondence", {})
        assert False, "expected denial"
    except GatewayDenialError:
        pass
    # The denial is audited.
    assert len(gateway.unauthorised_attempts()) == 1


# ---------------------------------------------------------------------------
# Gateway: operation not in catalogue is denied (e.g. autonomous gmail send)
# ---------------------------------------------------------------------------
def test_gateway_denies_forbidden_operation(db, gateway):
    reg = T.register_agent(db, name="Sender", canonical_id="SAM-AG-064",
                           position_id="TEC-064", department="Technology, MCP & AgentOps",
                           role="Test", reports_to="SAM-AG-007", human_owner="Founder")
    w01_register(db, reg["agent_id"])
    w02_configure(db, reg["agent_id"], tools=["gmail"])
    agent = T.get_agent(db, reg["agent_id"])
    # 'send_email' is NOT in the catalogue (no autonomous external sending).
    try:
        gateway.execute(agent, "gmail", "send_email", {"to": "x@y.z"})
        assert False, "expected denial"
    except GatewayDenialError as exc:
        assert "not allowed" in exc.reason