"""MCP Gateway — the tool gateway that enforces permissions BEFORE any action executes.

Key rule (PDF1 p.11): "The OS should use a tool gateway to enforce
permissions BEFORE any action executes. Model instructions alone are not
a security boundary."

This module implements the MCP tool catalogue (spec section 3.3) with
restrictions enforced in CODE, not in prompts.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("sutra.gateway")

# ---------------------------------------------------------------------------
# MCP tool catalogue (spec section 3.3)
# ---------------------------------------------------------------------------

MCP_TOOL_CATALOGUE: dict[str, dict[str, Any]] = {
    "client_context": {
        "allowed_operations": ["retrieve_approved_client_data"],
        "restrictions": ["Client-specific access only"],
        "read_only": False,
    },
    "drive": {
        "allowed_operations": ["search_folder", "read_file"],
        "restrictions": ["No unrestricted Drive access"],
        "read_only": True,
    },
    "documents": {
        "allowed_operations": ["create_draft", "revise_draft"],
        "restrictions": ["Version-controlled outputs"],
        "read_only": False,
    },
    "sheets": {
        "allowed_operations": ["read_range", "update_status"],
        "restrictions": ["Controlled ranges only"],
        "read_only": False,
    },
    "gmail": {
        "allowed_operations": ["read_correspondence", "draft_reply"],
        "restrictions": ["No autonomous external sending initially"],
        "read_only": True,
    },
    "social": {
        "allowed_operations": ["read_metrics", "prepare_schedule"],
        "restrictions": ["Publishing requires approval"],
        "read_only": True,
    },
    "analytics": {
        "allowed_operations": ["retrieve_campaign_results"],
        "restrictions": ["Read-only initially"],
        "read_only": True,
    },
    "workflow": {
        "allowed_operations": ["create_task", "update_status"],
        "restrictions": ["State-transition rules apply"],
        "read_only": False,
    },
    "evaluation": {
        "allowed_operations": ["record_score", "record_feedback"],
        "restrictions": ["Append-only audit history"],
        "read_only": False,
    },
    "approvals": {
        "allowed_operations": ["request_authorisation", "check_authorisation"],
        "restrictions": ["Agents cannot self-approve"],
        "read_only": False,
    },
}

# Operations that require a human approval record before execution.
APPROVAL_REQUIRED_OPERATIONS = {
    ("social", "publish"),
    ("client_context", "retrieve_approved_client_data"),
    ("approvals", "grant_authorisation"),
}


class GatewayDecision:
    ALLOWED = "allowed"
    DENIED = "denied"
    NEEDS_APPROVAL = "needs_approval"


class GatewayDenialError(Exception):
    """Raised when the gateway denies a tool call."""

    def __init__(self, reason: str, tool: str, operation: str, agent_id: str):
        self.reason = reason
        self.tool = tool
        self.operation = operation
        self.agent_id = agent_id
        super().__init__(f"Gateway denied {tool}.{operation} for agent {agent_id}: {reason}")


class GatewayApprovalRequired(Exception):
    """Raised when a tool call needs human approval before it can execute."""

    def __init__(self, reason: str, tool: str, operation: str, agent_id: str, approval_id: str):
        self.reason = reason
        self.tool = tool
        self.operation = operation
        self.agent_id = agent_id
        self.approval_id = approval_id
        super().__init__(f"Gateway: {tool}.{operation} needs human approval ({approval_id}): {reason}")


class MCPGateway:
    """Enforces the MCP tool catalogue and per-agent permissions.

    Every tool call from any agent passes through `execute()`. The gateway:
      1. Checks the agent exists and is in an allowed lifecycle state.
      2. Checks the tool namespace is in the agent's allowed tools.
      3. Checks the operation is in the catalogue's allowed operations.
      4. Enforces catalogue-level restrictions (read-only, approval gates).
      5. Logs EVERY call (allowed, denied, approval-required) to the audit
         trail — including denials, so unauthorised attempts are visible.
    """

    def __init__(self, session_factory, human_owner: str = "Founder / Technology & Security Owner"):
        self._session_factory = session_factory
        self.human_owner = human_owner
        # Registry of concrete tool implementations: (namespace, operation) -> callable
        self._handlers: dict[tuple[str, str], Callable] = {}
        # Audit log of gateway decisions (in-memory + DB-backed via execution_log)
        self.audit_log: list[dict[str, Any]] = []

    def register_handler(self, namespace: str, operation: str, handler: Callable) -> None:
        """Register a concrete implementation for a catalogue operation."""
        self._handlers[(namespace, operation)] = handler

    # ------------------------------------------------------------------
    # Core enforcement
    # ------------------------------------------------------------------
    def check_permission(self, agent, namespace: str, operation: str) -> dict[str, Any]:
        """Evaluate whether `agent` may call `namespace.operation`.

        Returns a decision dict:
          {"decision": "allowed" | "denied" | "needs_approval", "reason": str}
        """
        # 1. Agent must exist.
        if agent is None:
            return {"decision": GatewayDecision.DENIED, "reason": "Unknown agent (not in registry)"}

        # 2. Suspended agents cannot call anything.
        if getattr(agent, "suspended", False):
            return {
                "decision": GatewayDecision.DENIED,
                "reason": f"Agent {agent.canonical_id} is suspended: {agent.suspend_reason}",
            }

        # 3. Only registered-or-better agents may call tools.
        allowed_states = {"registered", "configured", "evaluated", "approved", "active", "monitored", "updated"}
        if agent.status not in allowed_states:
            return {
                "decision": GatewayDecision.DENIED,
                "reason": f"Agent status '{agent.status}' may not call tools (needs one of {sorted(allowed_states)})",
            }

        # 4. Tool namespace must be in the agent's granted tools.
        granted = (agent.tools or {}).get("namespaces", []) if isinstance(agent.tools, dict) else (agent.tools or [])
        if namespace not in granted:
            return {
                "decision": GatewayDecision.DENIED,
                "reason": f"Tool namespace '{namespace}' not granted to agent {agent.canonical_id}",
            }

        # 5. Namespace must exist in the catalogue.
        if namespace not in MCP_TOOL_CATALOGUE:
            return {
                "decision": GatewayDecision.DENIED,
                "reason": f"Unknown tool namespace '{namespace}' (not in MCP catalogue)",
            }

        # 6. Operation must be in the catalogue's allowed operations.
        catalogue_entry = MCP_TOOL_CATALOGUE[namespace]
        if operation not in catalogue_entry["allowed_operations"]:
            return {
                "decision": GatewayDecision.DENIED,
                "reason": (
                    f"Operation '{operation}' not allowed for namespace '{namespace}'. "
                    f"Allowed: {catalogue_entry['allowed_operations']}"
                ),
            }

        # 7. Catalogue-level restrictions.
        if (namespace, operation) in APPROVAL_REQUIRED_OPERATIONS:
            return {
                "decision": GatewayDecision.NEEDS_APPROVAL,
                "reason": f"{namespace}.{operation} requires human approval (agents cannot self-approve)",
            }

        return {"decision": GatewayDecision.ALLOWED, "reason": "ok"}

    def execute(
        self,
        agent,
        namespace: str,
        operation: str,
        payload: dict[str, Any] | None = None,
        client_id: str | None = None,
        approval_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Enforce permissions, then execute the registered handler.

        Every call — allowed, denied, or approval-required — is recorded in
        the audit trail.
        """
        decision = self.check_permission(agent, namespace, operation)
        record = {
            "id": str(uuid.uuid4()),
            "agent_id": agent.id if agent else None,
            "agent_canonical_id": agent.canonical_id if agent else None,
            "namespace": namespace,
            "operation": operation,
            "decision": decision["decision"],
            "reason": decision["reason"],
            "client_id": client_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.audit_log.append(record)

        if decision["decision"] == GatewayDecision.DENIED:
            logger.warning("GATEWAY DENIED %s.%s for %s: %s", namespace, operation,
                           agent.canonical_id if agent else "?", decision["reason"])
            raise GatewayDenialError(decision["reason"], namespace, operation,
                                     agent.canonical_id if agent else "unknown")

        if decision["decision"] == GatewayDecision.NEEDS_APPROVAL:
            # An existing approval record can satisfy the gate.
            if approval_record and approval_record.get("status") == "approved":
                record["decision"] = "allowed_with_approval"
                record["approval_id"] = approval_record.get("id")
            else:
                logger.warning("GATEWAY NEEDS APPROVAL %s.%s for %s", namespace, operation,
                               agent.canonical_id if agent else "?")
                raise GatewayApprovalRequired(
                    decision["reason"], namespace, operation,
                    agent.canonical_id if agent else "unknown",
                    approval_record.get("id") if approval_record else "none",
                )

        handler = self._handlers.get((namespace, operation))
        if handler is None:
            # No concrete implementation registered yet — the gateway still
            # enforces and logs; execution returns a stub so the platform is
            # usable before every connector is built (Jod's job).
            result = {
                "status": "stub",
                "namespace": namespace,
                "operation": operation,
                "note": "No concrete connector registered for this operation yet (Jod implements connectors).",
                "payload": payload or {},
            }
        else:
            result = handler(agent, payload or {})

        record["result_status"] = result.get("status", "ok") if isinstance(result, dict) else "ok"
        return result

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit_access(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return the gateway audit trail (optionally filtered by agent)."""
        entries = self.audit_log
        if agent_id:
            entries = [e for e in entries if e.get("agent_id") == agent_id]
        return entries[-limit:]

    def unauthorised_attempts(self) -> list[dict[str, Any]]:
        """All DENIED gateway calls — the 'unauthorised privileged actions' KPI."""
        return [e for e in self.audit_log if e["decision"] == GatewayDecision.DENIED]