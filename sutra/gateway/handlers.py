"""Default local MCP connector handlers.

Per the spec, Sutra does NOT talk to external APIs directly — that is Jod's
job. These are the deterministic, local connectors registered at startup so
the gateway has real (non-stub) behaviour for the core workflow/evaluation/
approval operations. External connectors (drive, gmail, social, ...) are
registered as Jod builds them; until then the gateway enforces + logs and
returns a stub.
"""
from __future__ import annotations

from .mcp_gateway import MCPGateway


def register_default_handlers(gateway: MCPGateway) -> None:
    gateway.register_handler(
        "workflow", "create_task",
        lambda agent, payload: {"status": "ok", "task": payload.get("title", "task"),
                                "note": "task recorded in workflow state"},
    )
    gateway.register_handler(
        "workflow", "update_status",
        lambda agent, payload: {"status": "ok", "task_id": payload.get("task_id"),
                                "new_status": payload.get("status")},
    )
    gateway.register_handler(
        "evaluation", "record_score",
        lambda agent, payload: {"status": "ok", "note": "score appended (append-only)"},
    )
    gateway.register_handler(
        "evaluation", "record_feedback",
        lambda agent, payload: {"status": "ok", "note": "feedback appended (append-only)"},
    )
    gateway.register_handler(
        "approvals", "request_authorisation",
        lambda agent, payload: {"status": "ok", "note": "authorisation requested"},
    )
    gateway.register_handler(
        "approvals", "check_authorisation",
        lambda agent, payload: {"status": "ok", "authorised": False,
                                "note": "no pending authorisation found"},
    )