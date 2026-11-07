"""TEC-P40 — Platform Improvement Roadmap (spec section 8, W02).

Steps (from the spec):
 1. Collect open improvement items
 2. Prioritise by risk (security > reliability > cost > convenience)
 3. Map each item to an owner agent
 4. Define milestones and success measures
 5. Check dependencies
 6. Prepare the updated roadmap
 7. Route material changes for human approval
 8. Publish the roadmap to the control panel (Niyantrak)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import Report

# Priority ordering (spec: security > reliability > cost > convenience).
RISK_ORDER = {"security": 0, "reliability": 1, "cost": 2, "convenience": 3}


def tec_p40_roadmap_update(db: Session, *, items: list[dict[str, Any]] | None = None,
                           board_priorities: list[str] | None = None) -> dict[str, Any]:
    """Build the prioritised, versioned platform improvement roadmap.

    Each item: {"title": str, "risk": security|reliability|cost|convenience,
                "owner": str, "milestone": str, "success_measure": str,
                "depends_on": str?}
    """
    items = items or []
    for i, item in enumerate(items, 1):
        item.setdefault("id", f"PLAT-{i:03d}")
        item.setdefault("risk", "convenience")
        item.setdefault("owner", "unassigned")
        item.setdefault("milestone", "TBD")
        item.setdefault("success_measure", "TBD")
        item.setdefault("depends_on", None)

    # Prioritise: risk first, then dependencies (blocked items go last).
    items.sort(key=lambda it: (RISK_ORDER.get(it["risk"], 9), bool(it.get("depends_on"))))

    material_changes = [it for it in items if it["risk"] in ("security", "reliability")]
    version = f"v{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"

    roadmap = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "board_priorities": board_priorities or [],
        "items": items,
        "material_changes_routed_for_approval": [it["id"] for it in material_changes],
    }

    report = Report(
        kind="platform_roadmap",
        title=f"Platform Improvement Roadmap {version}",
        body=roadmap,
        routed_to=["Niyantrak (control panel)", "Human Board" if material_changes else None],
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "status": "published",
        "roadmap_id": report.id,
        "version": version,
        "items": items,
        "material_changes_routed_for_approval": roadmap["material_changes_routed_for_approval"],
        "note": "Material (security/reliability) changes routed for human approval.",
    }