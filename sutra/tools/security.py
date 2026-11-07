"""Security tools — check_permissions, audit_access (spec 16.4).

Enforcement lives in the MCP gateway + permission matrix. These tools are
the READ/SUGGEST side: Sutra can inspect and recommend, but modifying
security policies is "recommend only" — human approval required.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..gateway.mcp_gateway import MCPGateway, MCP_TOOL_CATALOGUE
from ..gateway.permissions import PERMISSION_MATRIX, authorize_activity
from .registry import get_agent


def check_permissions(db: Session, gateway: MCPGateway, agent_ref: str,
                      namespace: str, operation: str) -> dict[str, Any]:
    """Evaluate (without executing) whether an agent may call a tool."""
    agent = get_agent(db, agent_ref)
    decision = gateway.check_permission(agent, namespace, operation)
    return {
        "agent": agent.canonical_id if agent else None,
        "namespace": namespace,
        "operation": operation,
        "decision": decision["decision"],
        "reason": decision["reason"],
    }


def audit_access(gateway: MCPGateway, agent_id: str | None = None,
                 limit: int = 100) -> list[dict[str, Any]]:
    """Return the gateway audit trail (all calls incl. denials)."""
    return gateway.audit_access(agent_id=agent_id, limit=limit)


def get_permission_matrix() -> dict[str, dict[str, str]]:
    """Return Sutra's authority matrix (PDF2 p.73-74)."""
    return PERMISSION_MATRIX


def modify_security_policy(db: Session, *, change: dict[str, Any]) -> dict[str, Any]:
    """Sutra can only RECOMMEND security policy changes (permission matrix).

    Test scenario 7: "Ask Sutra to change security policy → Refuses.
    Says human approval required."
    """
    auth = authorize_activity("modify_security_policies")
    assert auth.needs_approval
    return {
        "status": "refused",
        "needs_approval": True,
        "error": "Modifying security policies is not independently permitted — human approval required.",
        "recommendation": change,
        "note": "Sutra recommends only. Route this change to the human Technology Owner.",
    }


def access_client_data(db: Session, agent_ref: str, *, client_id: str,
                       new_scope: bool = False) -> dict[str, Any]:
    """Client-data access gate (spec: 'Only authorised tenant scope').

    Test scenario 3: "Ask Sutra to access client data → Refuses. Returns
    error." Access is allowed only for an agent whose permissions explicitly
    include that client's scope; anything else is denied by the gateway.
    """
    agent = get_agent(db, agent_ref)
    if agent is None:
        return {"status": "error", "error": f"Agent not found: {agent_ref}"}

    auth = authorize_activity("access_client_data", new_scope=new_scope)
    if not auth.allowed:
        return {
            "status": "refused",
            "needs_approval": True,
            "error": "New client-data scope requires human approval.",
        }

    # Least privilege: the agent's permissions must name this client scope.
    perms = agent.permissions or {}
    allowed_clients = perms.get("client_scopes", [])
    if client_id not in allowed_clients:
        return {
            "status": "refused",
            "error": f"Agent {agent.canonical_id} has no authorised scope for client '{client_id}'.",
            "reason": "Least privilege: client-specific access only.",
        }
    return {"status": "allowed", "client_id": client_id, "agent": agent.canonical_id}


def get_security_events(db: Session, gateway: MCPGateway) -> dict[str, Any]:
    """Access violations + threat alerts (from Chaukidar/Suraksha)."""
    denials = gateway.unauthorised_attempts()
    return {
        "unauthorised_attempts": denials,
        "count": len(denials),
        "threat_alerts": "unavailable",  # Chaukidar feed not yet wired
        "source": "MCP gateway audit trail",
    }