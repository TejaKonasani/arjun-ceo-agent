"""Seed the platform database with Sutra's own registry record + the
Release 0 team (16 agents) as DRAFTS (status: proposed).

Run:  python -m sutra.seed
"""
from __future__ import annotations

from .database import SessionLocal, init_db
from .tools import register_agent

# Release 0 team (PDF2 p.77) — the 16 tech agents Sutra leads.
RELEASE_0_TEAM = [
    ("Sutra", "SAM-AG-007", "TEC-001", "AI Chief Technology Officer (AI CTO)"),
    ("Vinyas", "SAM-AG-008", "TEC-002", "Platform Architect"),
    ("Setubandh", "SAM-AG-009", "TEC-003", "MCP & Systems Integration Engineer"),
    ("Yantra", "SAM-AG-010", "TEC-004", "Agent Runtime & Workflow Orchestration"),
    ("Smaran", "SAM-AG-011", "TEC-005", "Knowledge & Context Infrastructure"),
    ("Suraksha", "SAM-AG-012", "TEC-006", "Security, Access & Reliability"),
    ("Niyantrak", "SAM-AG-013", "TEC-007", "AgentOps & Digital Workforce Systems"),
    ("Pehchaan", "SAM-AG-014", "TEC-008", "Agent Identity & Registry"),
    ("Jod", "SAM-AG-015", "TEC-009", "MCP Connectors & API Integration"),
    ("Adhikar", "SAM-AG-016", "TEC-010", "Tool Permissions & Access Control"),
    ("Pravahika", "SAM-AG-017", "TEC-011", "Workflow Runtime & Execution"),
    ("Sandarbhika", "SAM-AG-018", "TEC-012", "Context Assembly & Retrieval"),
    ("Nirikshak", "SAM-AG-019", "TEC-013", "Observability & Execution Telemetry"),
    ("Parikshak", "SAM-AG-020", "TEC-014", "Agent Testing & Evaluation Engineering"),
    ("Sanskaran", "SAM-AG-021", "TEC-015", "Agent Versioning & Release Management"),
    ("Chaukidar", "SAM-AG-022", "TEC-016", "Security Monitoring & Threat Detection"),
]


def seed() -> dict:
    init_db()
    created, skipped = [], []
    with SessionLocal() as db:
        for name, canonical, position, role in RELEASE_0_TEAM:
            from .tools import get_agent
            if get_agent(db, canonical) is not None:
                skipped.append(canonical)
                continue
            result = register_agent(
                db,
                name=name,
                canonical_id=canonical,
                position_id=position,
                department="Technology, MCP & AgentOps",
                role=role,
                reports_to="SAM-AG-001" if name == "Sutra" else "SAM-AG-007",
                evaluator="SAM-AG-029",
                human_owner="Founder / Designated Technology & Security Owner",
            )
            (created if result["status"] == "registered_draft" else skipped).append(canonical)
    return {"created": created, "skipped": skipped}


if __name__ == "__main__":
    import json

    print(json.dumps(seed(), indent=2))