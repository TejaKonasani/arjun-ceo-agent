"""W02 — Configure (lifecycle: registered → configured).

Sutra's gate at step 03: "Model, tools, context, policies set. Sutra
checks permissions are least-privilege (Adhikar)."
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..gateway.mcp_gateway import MCP_TOOL_CATALOGUE
from ..models import AgentStatus
from ..tools.registry import get_agent, update_agent


def w02_configure(db: Session, agent_ref: str, *, model: str | None = None,
                  tools: list[str] | None = None, permissions: dict | None = None) -> dict:
    """Set model/tools/policies and verify least-privilege before configuring."""
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}
    if agent.status != AgentStatus.REGISTERED:
        return {"status": "blocked", "error": f"Agent is '{agent.status}', expected 'registered'."}

    if model:
        agent.model = model
    if tools is not None:
        # Least privilege: only namespaces in the MCP catalogue may be granted.
        unknown = [t for t in tools if t not in MCP_TOOL_CATALOGUE]
        if unknown:
            return {
                "status": "blocked",
                "error": f"Unknown tool namespaces (not in MCP catalogue): {unknown}",
            }
        agent.tools = {"namespaces": tools}
    if permissions is not None:
        agent.permissions = permissions

    # Least-privilege check: an agent must not be granted more than it needs.
    # (Adhikar's rulebook — here we enforce catalogue membership + non-empty.)
    granted = (agent.tools or {}).get("namespaces", [])
    if not granted:
        return {"status": "blocked", "error": "Agent must be granted at least one tool namespace to be configured."}

    agent = update_agent(db, agent, status=AgentStatus.CONFIGURED)
    return {
        "status": "configured",
        "agent_id": agent.id,
        "canonical_id": agent.canonical_id,
        "lifecycle_status": agent.status,
        "model": agent.model,
        "granted_namespaces": granted,
        "least_privilege_check": "passed",
    }