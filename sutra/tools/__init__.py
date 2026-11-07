"""Sutra's tools (spec 16.4) — the functions the CTO agent calls."""
from .registry import register_agent, get_agent, list_agents, update_agent, delete_agent
from .deploy import deploy_agent, rollback_agent, suspend_agent
from .monitor import get_agent_health, get_system_metrics
from .security import (
    check_permissions,
    audit_access,
    get_permission_matrix,
    modify_security_policy,
    access_client_data,
    get_security_events,
)
from .incident import (
    log_incident,
    escalate_incident,
    get_incident_log,
    contain_incident,
    resolve_incident,
    close_incident,
)

__all__ = [
    "register_agent", "get_agent", "list_agents", "update_agent", "delete_agent",
    "deploy_agent", "rollback_agent", "suspend_agent",
    "get_agent_health", "get_system_metrics",
    "check_permissions", "audit_access", "get_permission_matrix",
    "modify_security_policy", "access_client_data", "get_security_events",
    "log_incident", "escalate_incident", "get_incident_log",
    "contain_incident", "resolve_incident", "close_incident",
]