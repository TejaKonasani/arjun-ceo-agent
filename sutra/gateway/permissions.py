"""Sutra's permission matrix, enforced at the SYSTEM level (spec section 4).

PDF2 p.73-74: the authority matrix. This module encodes it as data and
provides `authorize_activity()` which the tools and workflows call BEFORE
acting. A prompt instruction is NOT a security boundary — this code is.
"""
from __future__ import annotations

from typing import Any

# activity -> (authority, human_approval_needed)
#   authority: "permitted" | "not_permitted" | "conditional"
#   human_approval_needed: "no" | "yes" | "case_by_case" | "escalation"
PERMISSION_MATRIX: dict[str, dict[str, str]] = {
    "register_agent": {"authority": "permitted", "human_approval_needed": "no",
                       "note": "Review before activation"},
    "configure_tools": {"authority": "permitted", "human_approval_needed": "no",
                        "note": "Within predefined limits"},
    "grant_privileged_tools": {"authority": "not_permitted", "human_approval_needed": "yes"},
    "grant_production_credentials": {"authority": "not_permitted", "human_approval_needed": "yes"},
    "execute_approved_workflows": {"authority": "permitted", "human_approval_needed": "no"},
    "sensitive_external_actions": {"authority": "conditional", "human_approval_needed": "case_by_case"},
    "change_model_routing": {"authority": "conditional", "human_approval_needed": "yes_if_material"},
    "deploy_agent_version": {"authority": "conditional", "human_approval_needed": "yes",
                             "note": "Prepare and test; production release approval"},
    "suspend_unsafe_workflow": {"authority": "permitted", "human_approval_needed": "no",
                                "note": "Emergency rules; immediate notification to human"},
    "access_client_data": {"authority": "conditional", "human_approval_needed": "yes_if_new_scope"},
    "modify_security_policies": {"authority": "conditional", "human_approval_needed": "yes",
                                 "note": "Recommend only"},
    "delete_production_data": {"authority": "not_permitted", "human_approval_needed": "yes"},
    "execute_rollback": {"authority": "conditional", "human_approval_needed": "escalation",
                         "note": "Within approved emergency runbook"},
    "restore_from_backup": {"authority": "conditional", "human_approval_needed": "yes",
                            "note": "Prepare and verify; authorised recovery approval"},
}


class AuthorizationResult:
    def __init__(self, allowed: bool, needs_approval: bool, reason: str,
                 approval_activity: str | None = None):
        self.allowed = allowed
        self.needs_approval = needs_approval
        self.reason = reason
        self.approval_activity = approval_activity  # activity key to route for approval

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "needs_approval": self.needs_approval,
            "reason": self.reason,
            "approval_activity": self.approval_activity,
        }


def authorize_activity(activity: str, *, material_risk: bool = False,
                       new_scope: bool = False,
                       emergency_runbook_approved: bool = False) -> AuthorizationResult:
    """Check Sutra's authority for `activity` against the permission matrix."""
    entry = PERMISSION_MATRIX.get(activity)
    if entry is None:
        return AuthorizationResult(False, True, f"Unknown activity '{activity}' — default deny, route to human",
                                   approval_activity=activity)

    authority = entry["authority"]
    approval_needed = entry["human_approval_needed"]

    if authority == "permitted":
        if approval_needed == "no":
            return AuthorizationResult(True, False, f"Permitted: {entry.get('note', '')}".strip())
        # permitted but with a note (e.g. suspend -> immediate notification)
        return AuthorizationResult(True, False, f"Permitted (notify human): {entry.get('note', '')}")

    if authority == "not_permitted":
        return AuthorizationResult(False, True,
                                   f"Not independently permitted — human approval required: {activity}",
                                   approval_activity=activity)

    # conditional
    if approval_needed == "yes":
        return AuthorizationResult(False, True, f"Human approval required: {activity}",
                                   approval_activity=activity)
    if approval_needed == "case_by_case":
        return AuthorizationResult(False, True, f"Case-by-case human approval required: {activity}",
                                   approval_activity=activity)
    if approval_needed == "yes_if_material":
        if material_risk:
            return AuthorizationResult(False, True, "Material risk change — human approval required",
                                       approval_activity=activity)
        return AuthorizationResult(True, False, "Within approved, tested policy (non-material)")
    if approval_needed == "yes_if_new_scope":
        if new_scope:
            return AuthorizationResult(False, True, "New client-data scope — human approval required",
                                       approval_activity=activity)
        return AuthorizationResult(True, False, "Within authorised tenant scope")
    if approval_needed == "escalation":
        if emergency_runbook_approved:
            return AuthorizationResult(True, False, "Within approved emergency runbook (escalation + post-review)")
        return AuthorizationResult(False, True, "Rollback requires approved emergency runbook",
                                   approval_activity=activity)

    return AuthorizationResult(False, True, f"Unresolved authority for {activity} — route to human",
                               approval_activity=activity)