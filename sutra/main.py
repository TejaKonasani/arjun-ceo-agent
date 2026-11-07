"""FastAPI entry point — the Sutra platform API + dashboard.

Run:
    uvicorn sutra.main:app --host 0.0.0.0 --port 8000

Dashboard: http://localhost:8000/  (Sutra — Technology Operations Dashboard)
API docs:  http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import tools as T
from .agents import OllamaClient, SutraAgent
from .config import load_sutra_config
from .database import SessionLocal, get_session, init_db
from .gateway import MCPGateway, register_default_handlers
from .workflows import (
    human_approve,
    record_evaluation,
    request_deployment_approval,
    tec_p39_monthly_review,
    tec_p40_roadmap_update,
    w01_register,
    w02_configure,
    w03_deploy,
    w04_rollback,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sutra.api")


# ---------------------------------------------------------------------------
# App state: gateway + agent (singletons)
# ---------------------------------------------------------------------------
class AppState:
    def __init__(self):
        cfg = load_sutra_config()
        model_cfg = cfg.get("model", {})
        self.human_owner = cfg.get("human_owner", "Founder / Technology & Security Owner")
        self.llm = OllamaClient(
            endpoint=model_cfg.get("endpoint", "http://localhost:11434"),
            model=model_cfg.get("name", "llama3.1:8b"),
        )
        self.gateway = MCPGateway(SessionLocal, human_owner=self.human_owner)
        register_default_handlers(self.gateway)
        self.agent = SutraAgent(self.gateway, self.llm, human_owner=self.human_owner)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.sutra = AppState()
    # Seed Sutra's own registry record if missing (SAM-AG-007).
    _seed_sutra(app.state.sutra)
    yield


app = FastAPI(
    title="SUTRA — AI Chief Technology Officer Platform",
    description="Minimum Secure Agentic Platform (Release 0). Agent registry, MCP "
                "gateway, deployment gates, incidents, telemetry, and Sutra's dashboard.",
    version="1.0.0",
    lifespan=lifespan,
)


def _seed_sutra(state: AppState) -> None:
    with SessionLocal() as db:
        existing = T.get_agent(db, "SAM-AG-007")
        if existing is None:
            T.register_agent(
                db,
                name="Sutra",
                canonical_id="SAM-AG-007",
                position_id="TEC-001",
                department="Technology, MCP & AgentOps",
                role="AI Chief Technology Officer (AI CTO)",
                tools=["workflow", "evaluation", "approvals"],
                permissions={"client_scopes": []},
                reports_to="SAM-AG-001",
                evaluator="SAM-AG-029",  # Satya (Chief Assurance)
                human_owner=state.human_owner,
            )


def _state(request: Request) -> AppState:
    return request.app.state.sutra


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class TaskRequest(BaseModel):
    task: str
    client_id: str | None = None
    workflow_id: str | None = None


class RegisterAgentRequest(BaseModel):
    name: str
    role: str | None = None
    department: str | None = None
    position_id: str | None = None
    canonical_id: str | None = None
    tools: list[str] | None = None
    permissions: dict | None = None
    reports_to: str | None = None
    evaluator: str | None = None


class DeployRequest(BaseModel):
    environment: str = "production"
    approval_id: str | None = None


class SuspendRequest(BaseModel):
    reason: str


class RollbackRequest(BaseModel):
    reason: str
    runbook_approved: bool = False
    incident_id: str | None = None


class IncidentRequest(BaseModel):
    agent_ref: str | None = None
    severity: str
    description: str


class ConfigureRequest(BaseModel):
    model: str | None = None
    tools: list[str] | None = None
    permissions: dict | None = None


class EvaluationRequest(BaseModel):
    results: list[dict]
    evaluator: str = "SAM-AG-014"


class ApprovalDecision(BaseModel):
    approver: str


class GatewayCall(BaseModel):
    agent_ref: str
    namespace: str
    operation: str
    payload: dict | None = None
    client_id: str | None = None


class RoadmapRequest(BaseModel):
    items: list[dict] | None = None
    board_priorities: list[str] | None = None


# ---------------------------------------------------------------------------
# Sutra agent endpoints
# ---------------------------------------------------------------------------
@app.post("/api/agent/task")
def agent_task(req: TaskRequest, request: Request):
    """Run Sutra on a task (LangGraph agent + gateway-enforced tools)."""
    state = _state(request)
    return state.agent.run(req.task, client_id=req.client_id, workflow_id=req.workflow_id)


@app.get("/api/agent/health")
def agent_health(request: Request):
    """Sutra's own status, including model availability (no fake output)."""
    state = _state(request)
    return {
        "agent": "Sutra (SAM-AG-007)",
        "model": state.llm.model,
        "model_endpoint": state.llm.endpoint,
        "model_available": state.llm.is_available(),
        "note": "If model_available is false, Sutra degrades to deterministic "
                "routing and reports 'model unavailable' — no crash, no fake output.",
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@app.post("/api/agents")
def api_register_agent(req: RegisterAgentRequest, request: Request, db: Session = Depends(get_session)):
    state = _state(request)
    return T.register_agent(
        db, name=req.name, role=req.role, department=req.department,
        position_id=req.position_id, canonical_id=req.canonical_id,
        tools=req.tools, permissions=req.permissions, reports_to=req.reports_to,
        evaluator=req.evaluator, human_owner=state.human_owner,
    )


@app.get("/api/agents")
def api_list_agents(status: str | None = None, db: Session = Depends(get_session)):
    return {"agents": [a.to_dict() for a in T.list_agents(db, status=status)]}


@app.get("/api/agents/{agent_ref}")
def api_get_agent(agent_ref: str, db: Session = Depends(get_session)):
    a = T.get_agent(db, agent_ref)
    if a is None:
        raise HTTPException(404, "agent not found")
    return a.to_dict()


@app.post("/api/agents/{agent_ref}/register")
def api_w01_register(agent_ref: str, db: Session = Depends(get_session)):
    return w01_register(db, agent_ref)


@app.post("/api/agents/{agent_ref}/configure")
def api_w02_configure(agent_ref: str, req: ConfigureRequest, db: Session = Depends(get_session)):
    return w02_configure(db, agent_ref, model=req.model, tools=req.tools, permissions=req.permissions)


@app.post("/api/agents/{agent_ref}/evaluate")
def api_record_evaluation(agent_ref: str, req: EvaluationRequest, db: Session = Depends(get_session)):
    return record_evaluation(db, agent_ref, results=req.results, evaluator=req.evaluator)


@app.post("/api/agents/{agent_ref}/request-approval")
def api_request_approval(agent_ref: str, environment: str = "production",
                         db: Session = Depends(get_session)):
    return request_deployment_approval(db, agent_ref, environment=environment)


@app.post("/api/approvals/{approval_id}/decide")
def api_human_approve(approval_id: str, req: ApprovalDecision, db: Session = Depends(get_session)):
    return human_approve(db, approval_id, approver=req.approver)


@app.post("/api/agents/{agent_ref}/deploy")
def api_deploy(agent_ref: str, req: DeployRequest, db: Session = Depends(get_session)):
    return w03_deploy(db, agent_ref, environment=req.environment, approval_id=req.approval_id)


@app.post("/api/agents/{agent_ref}/suspend")
def api_suspend(agent_ref: str, req: SuspendRequest, db: Session = Depends(get_session)):
    return T.suspend_agent(db, agent_ref, reason=req.reason)


@app.post("/api/agents/{agent_ref}/rollback")
def api_rollback(agent_ref: str, req: RollbackRequest, db: Session = Depends(get_session)):
    return w04_rollback(db, agent_ref, reason=req.reason,
                        runbook_approved=req.runbook_approved, incident_id=req.incident_id)


# ---------------------------------------------------------------------------
# Monitoring / dashboard data
# ---------------------------------------------------------------------------
@app.get("/api/system/health")
def api_system_health(request: Request, db: Session = Depends(get_session)):
    state = _state(request)
    return T.get_system_metrics(db, gateway=state.gateway)


@app.get("/api/agents/{agent_ref}/health")
def api_agent_health(agent_ref: str, db: Session = Depends(get_session)):
    return T.get_agent_health(db, agent_ref)


@app.get("/api/executions")
def api_executions(limit: int = 50, db: Session = Depends(get_session)):
    from sqlalchemy import select
    from .models import ExecutionLog
    rows = db.execute(select(ExecutionLog).order_by(ExecutionLog.started_at.desc()).limit(limit)).scalars().all()
    return {"executions": [r.to_dict() for r in rows]}


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
@app.get("/api/security/events")
def api_security_events(request: Request, db: Session = Depends(get_session)):
    state = _state(request)
    return T.get_security_events(db, state.gateway)


@app.get("/api/security/audit")
def api_audit(request: Request, agent_id: str | None = None, limit: int = 100):
    state = _state(request)
    return {"audit": T.audit_access(state.gateway, agent_id=agent_id, limit=limit)}


@app.get("/api/security/permission-matrix")
def api_permission_matrix():
    return T.get_permission_matrix()


@app.post("/api/security/policy-change")
def api_policy_change(change: dict, db: Session = Depends(get_session)):
    return T.modify_security_policy(db, change=change)


@app.post("/api/gateway/call")
def api_gateway_call(req: GatewayCall, request: Request, db: Session = Depends(get_session)):
    """Execute a tool call THROUGH the MCP gateway (permissions enforced)."""
    state = _state(request)
    agent = T.get_agent(db, req.agent_ref)
    try:
        return state.gateway.execute(agent, req.namespace, req.operation,
                                     payload=req.payload, client_id=req.client_id)
    except Exception as exc:
        return {"status": "denied" if "denied" in str(exc).lower() else "blocked", "error": str(exc)}


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------
@app.post("/api/incidents")
def api_log_incident(req: IncidentRequest, db: Session = Depends(get_session)):
    return T.log_incident(db, agent_ref=req.agent_ref, severity=req.severity,
                          description=req.description)


@app.get("/api/incidents")
def api_incidents(include_closed: bool = True, db: Session = Depends(get_session)):
    return {"incidents": T.get_incident_log(db, include_closed=include_closed)}


# ---------------------------------------------------------------------------
# Standing processes
# ---------------------------------------------------------------------------
@app.post("/api/processes/tec-p39")
def api_tec_p39(request: Request, db: Session = Depends(get_session)):
    state = _state(request)
    return tec_p39_monthly_review(db, state.gateway)


@app.post("/api/processes/tec-p40")
def api_tec_p40(req: RoadmapRequest, db: Session = Depends(get_session)):
    return tec_p40_roadmap_update(db, items=req.items, board_priorities=req.board_priorities)


@app.get("/api/reports")
def api_reports(db: Session = Depends(get_session)):
    from sqlalchemy import select
    from .models import Report
    rows = db.execute(select(Report).order_by(Report.created_at.desc())).scalars().all()
    return {"reports": [r.to_dict() for r in rows]}


# ---------------------------------------------------------------------------
# Dashboard (spec section 7 — Sutra's "eyes")
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return _DASHBOARD_HTML


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SUTRA — Technology Operations Dashboard</title>
<style>
  :root { --bg:#0b1020; --card:#141b2e; --line:#243049; --txt:#e6ecf7; --dim:#8ea0bf;
          --ok:#34d399; --warn:#fbbf24; --bad:#f87171; --accent:#60a5fa; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:ui-sans-serif,system-segment,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--txt); }
  header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex;
           justify-content:space-between; align-items:center; }
  header h1 { font-size:18px; margin:0; letter-spacing:.4px; }
  header .sub { color:var(--dim); font-size:12px; margin-top:3px; }
  .chip { font-size:11px; padding:3px 10px; border-radius:999px; border:1px solid var(--line);
          color:var(--dim); }
  .chip.ok { color:var(--ok); border-color:var(--ok); }
  .chip.bad { color:var(--bad); border-color:var(--bad); }
  main { padding:20px 24px; display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
         gap:14px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .panel h2 { font-size:13px; margin:0 0 10px; color:var(--accent); text-transform:uppercase;
              letter-spacing:.6px; }
  .row { display:flex; justify-content:space-between; font-size:13px; padding:4px 0;
         border-bottom:1px dashed var(--line); }
  .row:last-child { border-bottom:none; }
  .row .k { color:var(--dim); }
  .row .v { font-variant-numeric:tabular-nums; }
  .v.pass { color:var(--ok); } .v.fail { color:var(--bad); }
  .v.unavail { color:var(--warn); font-style:italic; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th,td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight:600; }
  .badge { font-size:10px; padding:2px 7px; border-radius:999px; }
  .badge.pass { background:rgba(52,211,153,.15); color:var(--ok); }
  .badge.fail { background:rgba(248,113,113,.15); color:var(--bad); }
  .badge.unavail { background:rgba(251,191,36,.15); color:var(--warn); }
  footer { padding:14px 24px; color:var(--dim); font-size:11px; border-top:1px solid var(--line); }
  #refresh { cursor:pointer; background:none; border:1px solid var(--line); color:var(--txt);
             border-radius:8px; padding:6px 12px; font-size:12px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>SUTRA — Technology Operations Dashboard</h1>
    <div class="sub">AI CTO (SAM-AG-007) · Technology, MCP &amp; AgentOps · Release 0 — Minimum Secure Agentic Platform</div>
  </div>
  <div style="display:flex;gap:8px;align-items:center">
    <span class="chip" id="model-chip">model: …</span>
    <button id="refresh" onclick="load()">Refresh</button>
  </div>
</header>
<main id="grid"></main>
<footer>
  Sutra's dashboard (spec §7). Every metric that cannot be computed from real data is shown as
  <em>unavailable</em> — never invented. API: /docs · Data: /api/system/health
</footer>
<script>
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function v(x){
  if(x==='unavailable'||x===null||x===undefined) return '<span class="v unavail">unavailable</span>';
  return '<span class="v">'+esc(x)+'</span>';
}
function badge(s){
  s=String(s).toLowerCase();
  if(s==='pass') return '<span class="badge pass">PASS</span>';
  if(s==='fail') return '<span class="badge fail">FAIL</span>';
  return '<span class="badge unavail">'+esc(s)+'</span>';
}
function panel(title, rows){
  let h='<div class="panel"><h2>'+title+'</h2>';
  for(const [k,val] of rows){ h+='<div class="row"><span class="k">'+k+'</span>'+v(val)+'</div>'; }
  return h+'</div>';
}
async function load(){
  const [m, h] = await Promise.all([
    fetch('/api/agent/health').then(r=>r.json()),
    fetch('/api/system/health').then(r=>r.json()),
  ]);
  const chip=document.getElementById('model-chip');
  chip.textContent='model: '+(m.model_available?'available':'UNAVAILABLE (deterministic mode)');
  chip.className='chip '+(m.model_available?'ok':'bad');
  const g=document.getElementById('grid');
  let html='';
  html+=panel('Digital Workforce',[
    ['Registered',h.digital_workforce.registered],
    ['Active',h.digital_workforce.active],
    ['Restricted (suspended)',h.digital_workforce.restricted],
    ['Retired',h.digital_workforce.retired],
  ]);
  html+=panel('Workflow Execution',[
    ['Total runs',h.workflow_execution.total],
    ['Completed',h.workflow_execution.completed],
    ['Failed',h.workflow_execution.failed],
    ['Retried',h.workflow_execution.retried],
    ['Success rate',h.workflow_execution.success_rate],
  ]);
  html+=panel('MCP & Integrations',[
    ['Connected',h.mcp_integrations.connected],
    ['Degraded',h.mcp_integrations.degraded],
    ['Failed',h.mcp_integrations.failed],
  ]);
  html+=panel('Security & Permissions',[
    ['Unauthorised actions',h.security.unauthorised_actions],
    ['Open incidents',h.security.open_incidents],
    ['Critical open',h.security.critical_open],
    ['Policy violations',h.security.policy_violations],
  ]);
  html+=panel('Platform Reliability',[
    ['Availability',h.platform_reliability.availability],
    ['Latency p95 (ms)',h.platform_reliability.latency_p95_ms],
    ['Error rate',h.platform_reliability.error_rate],
  ]);
  html+=panel('AI Execution Economics',[
    ['Tokens used',h.ai_execution_economics.tokens_used],
    ['Tool costs',h.ai_execution_economics.tool_costs],
    ['Cost per task',h.ai_execution_economics.cost_per_task],
  ]);
  html+=panel('Versions & Releases',[
    ['Deployed',h.versions_releases.deployed],
    ['Testing',h.versions_releases.testing],
    ['Approved',h.versions_releases.approved],
    ['Rolled back',h.versions_releases.rolled_back],
  ]);
  g.innerHTML=html;
  loadKPIs();
}
async function loadKPIs(){
  const r=await fetch('/api/reports').then(r=>r.json());
  const monthly=(r.reports||[]).find(x=>x.kind==='monthly_tech_performance');
  const grid=document.getElementById('grid');
  if(!monthly){ return; }
  const rows=(monthly.body.scorecard||[]).map(k=>
    '<tr><td>'+esc(k.kpi)+'</td><td>'+esc(k.actual)+'</td><td>'+esc(k.target)+'</td><td>'+badge(k.status)+'</td><td>'+esc(k.source)+'</td></tr>'
  ).join('');
  const issues=(monthly.body.top_issues||[]).map((i,idx)=>
    '<tr><td>'+(idx+1)+'</td><td>'+esc(i.risk)+'</td><td>'+esc(i.issue)+'</td><td>'+esc(i.owner)+'</td></tr>').join('');
  const p='<div class="panel" style="grid-column:1/-1"><h2>KPI Scorecard — '+esc(monthly.period)+' (TEC-P39)</h2>'+
    '<table><tr><th>KPI</th><th>Actual</th><th>Target</th><th>Status</th><th>Source</th></tr>'+rows+'</table>'+
    '<h2 style="margin-top:14px">Top Issues (ranked by risk)</h2>'+
    '<table><tr><th>#</th><th>Risk</th><th>Issue</th><th>Owner</th></tr>'+issues+'</table></div>';
  grid.insertAdjacentHTML('beforeend',p);
}
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("sutra.main:app", host="0.0.0.0", port=8000, reload=False)