# Emergency Runbook — Sutra Platform (Release 0)

> **Status:** Draft v1.0 — requires human approval before activation
> (build checklist: "Emergency runbook written and approved").
> **Owner:** Sutra (SAM-AG-007) · **Approver:** Human Technology Owner

This runbook defines the ONLY sanctioned emergency actions Sutra may take
without prior approval. Every action is logged and the human Technology
Owner is notified immediately.

---

## RTO target
Critical workflow recovery within **30 minutes** (assumed per approved
runbook v1.0 — to be baseline-tested in the first 30 days).

## 1. Suspend an unsafe agent / workflow
**When:** An agent or workflow is causing harm, leaking data, or failing
critically in production.

**Authority:** ✅ Permitted under emergency rules (permission matrix).

**Steps:**
1. Confirm the failure (telemetry + incident evidence).
2. `suspend_agent(agent_id, reason)` — the MCP gateway immediately blocks
   all tool calls for the suspended agent.
3. The suspension is logged in the execution/audit trail.
4. **Immediately notify the human Technology Owner** (mandatory).
5. Record the incident with the full timeline.

**Rollback of the suspension:** Only after root cause is fixed and
Parikshak regression tests pass; requires human sign-off.

## 2. Roll back a bad agent version
**When:** A newly deployed version caused the incident.

**Authority:** ⚠️ Within this approved emergency runbook — escalation +
post-review required.

**Steps:**
1. Identify the bad version (`deployed_version` in the registry).
2. `rollback_agent(agent_id, reason, runbook_approved=True)`.
3. Verify the previous version is healthy (telemetry).
4. Escalate to the human Technology Owner with the incident ID.
5. Post-review: root cause (Pratikriya), corrective action, prevention —
   fed into the roadmap (TEC-P40).

## 3. What Sutra may NOT do in an emergency
- Delete production data (human approval required).
- Modify security policies (recommend only).
- Suppress or downgrade a security finding or incident.
- Approve his own changes or certify his own work.

## 4. Escalation contacts
| Role | Contact |
|---|---|
| Human Technology Owner | Founder / Designated Technology & Security Owner |
| AI CEO | Arjun (SAM-AG-001) |
| Independent assurance | Satya (SAM-AG-029) — reports to the human Board |