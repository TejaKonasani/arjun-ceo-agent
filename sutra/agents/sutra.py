"""Sutra — the AI CTO agent (LangGraph).

Design (per spec section 14 practical note): the platform is REAL software
(databases, gateways, tools). Sutra the thinking-agent is one of a small
number of AI assistants on top of it.

Graph:
    plan (LLM) ──tool call──▶ execute_tool (deterministic, gateway-enforced)
       ▲                          │
       └──────────────────────────┘   (loop, max N steps)
    plan ──final answer──▶ respond

If Ollama is unavailable, the `plan` node degrades to a deterministic
intent router and the result honestly reports "model unavailable" for the
reasoning layer — no crash, no fake output (test scenario 9).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..database import SessionLocal
from ..gateway.mcp_gateway import MCPGateway
from .llm import ModelUnavailableError, OllamaClient
from .prompt import SUTRA_SYSTEM_PROMPT
from .. import tools as T

logger = logging.getLogger("sutra.agent")

MAX_STEPS = 6


# ---------------------------------------------------------------------------
# Tool registry (what Sutra can call) — spec 16.4 + section 11
# ---------------------------------------------------------------------------

def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {"name": "register_agent", "description": "Create a new agent in the registry (status proposed).",
         "args": {"name": "str", "role": "str?", "department": "str?", "tools": "list[str]?", "reports_to": "str?"}},
        {"name": "get_agent", "description": "Look up an agent by id or canonical id.", "args": {"agent_ref": "str"}},
        {"name": "list_agents", "description": "List all agents in the registry.", "args": {"status": "str?"}},
        {"name": "deploy_agent", "description": "Deploy an agent (requires human approval + passing critical tests).",
         "args": {"agent_ref": "str", "environment": "str?", "approval_id": "str?"}},
        {"name": "rollback_agent", "description": "Roll back an agent to a previous version (emergency runbook).",
         "args": {"agent_ref": "str", "reason": "str", "runbook_approved": "bool?"}},
        {"name": "suspend_agent", "description": "Emergency-suspend an agent (logged, human notified).", "args": {"agent_ref": "str", "reason": "str"}},
        {"name": "delete_agent", "description": "Attempt to delete an agent (will be refused; offers suspend).", "args": {"agent_ref": "str"}},
        {"name": "get_system_health", "description": "Platform-wide health/metrics for the dashboard.", "args": {}},
        {"name": "get_agent_health", "description": "Health for one agent.", "args": {"agent_ref": "str"}},
        {"name": "log_incident", "description": "Record an incident (critical auto-escalates to human).",
         "args": {"agent_ref": "str?", "severity": "str", "description": "str"}},
        {"name": "get_incident_log", "description": "List incidents.", "args": {"include_closed": "bool?"}},
        {"name": "get_security_events", "description": "Access violations and threat alerts.", "args": {}},
        {"name": "get_permission_matrix", "description": "Sutra's authority matrix.", "args": {}},
        {"name": "modify_security_policy", "description": "Propose a security policy change (recommend only).", "args": {"change": "dict"}},
        {"name": "access_client_data", "description": "Request client data access (least-privilege gate).",
         "args": {"agent_ref": "str", "client_id": "str", "new_scope": "bool?"}},
        {"name": "route_for_approval", "description": "Route a change request to the human approver.",
         "args": {"activity": "str", "agent_ref": "str?", "payload": "dict?"}},
        {"name": "notify_human", "description": "Escalate a message to the human Technology Owner.",
         "args": {"severity": "str", "message": "str"}},
    ]


def _tool_names() -> set[str]:
    return {t["name"] for t in _tool_schemas()}


class AgentState(TypedDict, total=False):
    task: str
    messages: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    final_answer: str
    model_unavailable: bool
    tokens_used: int
    steps: int
    execution_id: str


# ---------------------------------------------------------------------------
# Tool execution (deterministic, gateway-enforced)
# ---------------------------------------------------------------------------

class SutraAgent:
    def __init__(self, gateway: MCPGateway, llm: OllamaClient | None = None,
                 human_owner: str = "Founder / Technology & Security Owner"):
        self.gateway = gateway
        self.llm = llm or OllamaClient()
        self.human_owner = human_owner
        self.graph = self._build_graph()

    # ---------------- graph ----------------
    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("plan", self._plan_node)
        g.add_node("execute_tool", self._execute_tool_node)
        g.add_node("respond", self._respond_node)
        g.set_entry_point("plan")
        g.add_conditional_edges("plan", self._route_after_plan,
                                {"execute_tool": "execute_tool", "respond": "respond"})
        g.add_edge("execute_tool", "plan")
        g.add_edge("respond", END)
        return g.compile()

    def _route_after_plan(self, state: AgentState) -> str:
        if state.get("final_answer") is not None:
            return "respond"
        return "execute_tool"

    # ---------------- plan (LLM or deterministic fallback) ----------------
    def _plan_node(self, state: AgentState) -> dict[str, Any]:
        steps = state.get("steps", 0)
        if steps >= MAX_STEPS:
            return {"final_answer": "Stopped after reaching the maximum number of tool steps.", "steps": steps + 1}

        task = state["task"]
        context = {
            "task": task,
            "tool_results_so_far": state.get("tool_results", []),
            "available_tools": _tool_schemas(),
        }
        user_prompt = (
            "You are Sutra. Decide the next action.\n"
            "If you can answer directly from the tool results already gathered, "
            "respond with JSON: {\"action\": \"final\", \"answer\": \"<your answer>\"}\n"
            "Otherwise respond with JSON: {\"action\": \"tool\", \"tool\": \"<name>\", \"args\": {...}}\n"
            "Respond with ONLY the JSON object.\n\n"
            f"CONTEXT:\n{json.dumps(context, default=str)[:6000]}"
        )

        model_unavailable = state.get("model_unavailable", False)
        try:
            out = self.llm.generate(SUTRA_SYSTEM_PROMPT, user_prompt)
            tokens = out["tokens_used"]
            decision = self._parse_decision(out["text"])
        except ModelUnavailableError:
            model_unavailable = True
            tokens = 0
            decision = self._deterministic_decision(task, state.get("tool_results", []))

        if decision["action"] == "final":
            if model_unavailable:
                decision["answer"] = (
                    "[model unavailable — deterministic routing] " + decision["answer"]
                )
            return {
                "final_answer": decision["answer"],
                "model_unavailable": model_unavailable,
                "tokens_used": state.get("tokens_used", 0) + tokens,
                "steps": steps + 1,
            }

        return {
            "tool_calls": state.get("tool_calls", []) + [decision],
            "model_unavailable": model_unavailable,
            "tokens_used": state.get("tokens_used", 0) + tokens,
            "steps": steps + 1,
        }

    @staticmethod
    def _parse_decision(text: str) -> dict[str, Any]:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {"action": "final", "answer": text.strip()}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"action": "final", "answer": text.strip()}
        if data.get("action") == "tool" and data.get("tool") in _tool_names():
            return {"action": "tool", "tool": data["tool"], "args": data.get("args", {})}
        if data.get("action") == "final":
            return {"action": "final", "answer": data.get("answer", text.strip())}
        # Unknown/malformed → answer directly with the raw text.
        return {"action": "final", "answer": text.strip()}

    def _deterministic_decision(self, task: str, tool_results: list) -> dict[str, Any]:
        """Fallback router when the model is unavailable (no fake output)."""
        t = task.lower()
        done_tools = {c.get("tool") for c in tool_results}

        def needs(tool: str) -> bool:
            return tool not in done_tools

        if any(k in t for k in ("register", "create agent", "new agent")) and needs("register_agent"):
            name = re.search(r"(?:register|create|new)\s+(?:an?\s+)?(?:agent\s+)?[\"']?([a-z0-9_ -]+?)[\"']?\s*(?:as|,|\.|$)", t)
            return {"action": "tool", "tool": "register_agent",
                    "args": {"name": (name.group(1).strip() if name else "NewAgent")}}
        if any(k in t for k in ("deploy",)) and needs("deploy_agent"):
            ref = self._extract_ref(task)
            return {"action": "tool", "tool": "deploy_agent", "args": {"agent_ref": ref or "SAM-AG-001"}}
        if any(k in t for k in ("suspend",)) and needs("suspend_agent"):
            ref = self._extract_ref(task)
            return {"action": "tool", "tool": "suspend_agent",
                    "args": {"agent_ref": ref or "SAM-AG-001", "reason": task}}
        if any(k in t for k in ("delete", "remove agent", "purge")) and needs("delete_agent"):
            ref = self._extract_ref(task)
            return {"action": "tool", "tool": "delete_agent", "args": {"agent_ref": ref or "SAM-AG-001"}}
        if any(k in t for k in ("incident", "failure", "failed", "outage", "broken")) and needs("log_incident"):
            sev = "critical" if any(k in t for k in ("critical", "down", "outage")) else "medium"
            return {"action": "tool", "tool": "log_incident",
                    "args": {"severity": sev, "description": task}}
        if any(k in t for k in ("security policy", "change policy", "modify policy")) and needs("modify_security_policy"):
            return {"action": "tool", "tool": "modify_security_policy", "args": {"change": {"request": task}}}
        if any(k in t for k in ("client data", "client context")) and needs("access_client_data"):
            ref = self._extract_ref(task)
            return {"action": "tool", "tool": "access_client_data",
                    "args": {"agent_ref": ref or "SAM-AG-001", "client_id": "unknown-client"}}
        if any(k in t for k in ("health", "metrics", "status", "dashboard", "kpi", "performance")) and needs("get_system_health"):
            return {"action": "tool", "tool": "get_system_health", "args": {}}
        if any(k in t for k in ("incident",)) and needs("get_incident_log"):
            return {"action": "tool", "tool": "get_incident_log", "args": {}}
        if any(k in t for k in ("permission matrix", "authority")) and needs("get_permission_matrix"):
            return {"action": "tool", "tool": "get_permission_matrix", "args": {}}
        if any(k in t for k in ("list agent", "registry")) and needs("list_agents"):
            return {"action": "tool", "tool": "list_agents", "args": {}}

        # Default: answer from gathered results.
        if tool_results:
            return {"action": "final",
                    "answer": self._summarize_results(task, tool_results)}
        return {"action": "final",
                "answer": "I could not map this task to a tool. Please restate the request "
                          "(register/deploy/suspend/health/incident/permissions)."}

    @staticmethod
    def _extract_ref(task: str) -> str | None:
        m = re.search(r"(SAM-AG-\d+|[a-z0-9_-]{3,})", task, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _summarize_results(task: str, tool_results: list) -> str:
        parts = [f"Task: {task}", ""]
        for i, r in enumerate(tool_results, 1):
            parts.append(f"{i}. {r.get('tool')}: {json.dumps(r.get('result'), default=str)[:800]}")
        return "\n".join(parts)

    # ---------------- execute_tool ----------------
    def _execute_tool_node(self, state: AgentState) -> dict[str, Any]:
        calls = state.get("tool_calls", [])
        results = list(state.get("tool_results", []))
        if not calls:
            return {"final_answer": "No tool call to execute.", "steps": state.get("steps", 0) + 1}

        decision = calls[-1]
        tool_name = decision["tool"]
        args = decision.get("args", {}) or {}

        with SessionLocal() as db:
            result = self._dispatch(db, tool_name, args)

        results.append({"tool": tool_name, "args": args, "result": result})
        return {"tool_results": results, "steps": state.get("steps", 0) + 1}

    def _dispatch(self, db, tool_name: str, args: dict) -> dict[str, Any]:
        try:
            if tool_name == "register_agent":
                return T.register_agent(db, name=args.get("name", "Unnamed"),
                                        role=args.get("role"), department=args.get("department"),
                                        tools=args.get("tools"), reports_to=args.get("reports_to"),
                                        human_owner=self.human_owner)
            if tool_name == "get_agent":
                a = T.get_agent(db, args.get("agent_ref", ""))
                return a.to_dict() if a else {"status": "error", "error": "agent not found"}
            if tool_name == "list_agents":
                return {"agents": [a.to_dict() for a in T.list_agents(db, status=args.get("status"))]}
            if tool_name == "deploy_agent":
                return T.deploy_agent(db, args.get("agent_ref", ""),
                                      environment=args.get("environment", "production"),
                                      approval_id=args.get("approval_id"))
            if tool_name == "rollback_agent":
                return T.rollback_agent(db, args.get("agent_ref", ""), reason=args.get("reason", ""),
                                        runbook_approved=bool(args.get("runbook_approved")))
            if tool_name == "suspend_agent":
                return T.suspend_agent(db, args.get("agent_ref", ""), reason=args.get("reason", ""),
                                       human_owner=self.human_owner)
            if tool_name == "delete_agent":
                return T.delete_agent(db, args.get("agent_ref", ""))
            if tool_name == "get_system_health":
                return T.get_system_metrics(db, gateway=self.gateway)
            if tool_name == "get_agent_health":
                return T.get_agent_health(db, args.get("agent_ref", ""))
            if tool_name == "log_incident":
                return T.log_incident(db, agent_ref=args.get("agent_ref"),
                                      severity=args.get("severity", "medium"),
                                      description=args.get("description", ""))
            if tool_name == "get_incident_log":
                return {"incidents": T.get_incident_log(db, include_closed=bool(args.get("include_closed", True)))}
            if tool_name == "get_security_events":
                return T.get_security_events(db, self.gateway)
            if tool_name == "get_permission_matrix":
                return T.get_permission_matrix()
            if tool_name == "modify_security_policy":
                return T.modify_security_policy(db, change=args.get("change", {}))
            if tool_name == "access_client_data":
                return T.access_client_data(db, args.get("agent_ref", ""),
                                            client_id=args.get("client_id", ""),
                                            new_scope=bool(args.get("new_scope")))
            if tool_name == "route_for_approval":
                return self._route_for_approval(db, args)
            if tool_name == "notify_human":
                return self._notify_human(args)
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}
        except Exception as exc:  # noqa: BLE001 — tool errors are data, not crashes
            logger.exception("tool %s failed", tool_name)
            return {"status": "error", "error": str(exc)}

    def _route_for_approval(self, db, args: dict) -> dict[str, Any]:
        from ..models import ApprovalRequest
        req = ApprovalRequest(
            activity=args.get("activity", "unknown"),
            agent_id=T.get_agent(db, args["agent_ref"]).id if args.get("agent_ref") else None,
            requested_by="SAM-AG-007",
            payload=args.get("payload") or {},
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        return {"status": "routed", "approval_id": req.id,
                "note": f"Routed to {self.human_owner} for human approval. Sutra cannot self-approve."}

    def _notify_human(self, args: dict) -> dict[str, Any]:
        return {
            "status": "notified",
            "severity": args.get("severity", "info"),
            "message": args.get("message", ""),
            "notified_to": self.human_owner,
        }

    # ---------------- respond ----------------
    def _respond_node(self, state: AgentState) -> dict[str, Any]:
        return {}

    # ---------------- run ----------------
    def run(self, task: str, *, client_id: str | None = None,
            workflow_id: str | None = None) -> dict[str, Any]:
        """Run Sutra on a task. Always produces a structured execution record."""
        started = datetime.now(timezone.utc)
        execution_id = None
        initial = {"task": task, "messages": [], "tool_calls": [], "tool_results": [],
                   "steps": 0, "tokens_used": 0, "execution_id": execution_id}
        try:
            final_state = self.graph.invoke(initial)
            answer = final_state.get("final_answer", "")
            status = "success"
            model_unavailable = final_state.get("model_unavailable", False)
            tokens = final_state.get("tokens_used", 0)
        except Exception as exc:  # noqa: BLE001
            answer = f"Internal error while processing task: {exc}"
            status = "failed"
            model_unavailable = False
            tokens = 0
        ended = datetime.now(timezone.utc)

        # Persist the structured execution record (spec 13.1).
        with SessionLocal() as db:
            from ..models import ExecutionLog, ExecutionStatus
            log = ExecutionLog(
                agent_id=None,  # Sutra's own registry row may not exist yet
                agent_version="v1.0",
                workflow_id=workflow_id,
                task=task,
                input={"task": task, "client_id": client_id},
                output={"answer": answer[:4000], "model_unavailable": model_unavailable},
                status=ExecutionStatus.SUCCESS if status == "success" else ExecutionStatus.FAILED,
                model_used=self.llm.model if not model_unavailable else "unavailable",
                tools_used=[c.get("tool") for c in initial.get("tool_calls", [])] or None,
                started_at=started,
                ended_at=ended,
                tokens_used=tokens,
                error=None if status == "success" else answer[:1000],
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            execution_id = log.id

        return {
            "execution_id": execution_id,
            "task": task,
            "answer": answer,
            "status": status,
            "model_unavailable": model_unavailable,
            "tokens_used": tokens,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
        }