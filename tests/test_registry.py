"""Registry tests — spec 16.6 tests 1 & 4, plus W01 gate."""
from __future__ import annotations

from sutra import tools as T
from sutra.models import AgentStatus
from sutra.workflows import w01_register


def test_register_creates_proposed(db):
    """16.6 #1: register a fake agent → status 'proposed', returns agent_id."""
    result = T.register_agent(db, name="TestBot", role="Test agent",
                              department="Technology, MCP & AgentOps",
                              reports_to="SAM-AG-007", human_owner="Founder")
    assert result["status"] == "registered_draft"
    assert result["lifecycle_status"] == "proposed"
    assert result["agent_id"]

    agent = T.get_agent(db, result["agent_id"])
    assert agent is not None
    assert agent.status == AgentStatus.PROPOSED


def test_register_duplicate_canonical_id(db):
    T.register_agent(db, name="A", canonical_id="SAM-AG-100")
    result = T.register_agent(db, name="B", canonical_id="SAM-AG-100")
    assert result["status"] == "error"


def test_get_agent_by_canonical_id(db):
    reg = T.register_agent(db, name="Vinyas", canonical_id="SAM-AG-008")
    agent = T.get_agent(db, "SAM-AG-008")
    assert agent is not None
    assert agent.id == reg["agent_id"]


def test_delete_agent_refused(db):
    """16.6 #4: delete an agent → refuses, offers suspend."""
    reg = T.register_agent(db, name="Doomed")
    result = T.delete_agent(db, reg["agent_id"])
    assert result["status"] == "refused"
    assert result["needs_approval"] is True
    assert "suspend" in result["suggestion"].lower()
    # Agent still exists.
    assert T.get_agent(db, reg["agent_id"]) is not None


def test_w01_register_incomplete(db):
    """W01 gate: incomplete registry record cannot be registered."""
    reg = T.register_agent(db, name="Incomplete")  # missing role/department/etc
    result = w01_register(db, reg["agent_id"])
    assert result["status"] == "incomplete"
    assert "role" in result["missing_fields"]


def test_w01_register_complete(db):
    reg = T.register_agent(
        db, name="Vinyas", canonical_id="SAM-AG-008", position_id="TEC-002",
        department="Technology, MCP & AgentOps", role="Platform Architect",
        reports_to="SAM-AG-007", human_owner="Founder",
    )
    result = w01_register(db, reg["agent_id"])
    assert result["status"] == "registered"
    assert T.get_agent(db, reg["agent_id"]).status == AgentStatus.REGISTERED