# agent/graph.py
# ── IMPORTS ──────────────────────────────────────────────────
from typing import Literal
from datetime import datetime
import json

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import IncidentState
from agent.tools import query_logs, lookup_runbook, page_team, post_slack_message, create_incident_ticket
from agent.llm import get_llm
from agent.reasoner import reason, CONFIDENCE_THRESHOLD, MAX_RETRIES
from agent.metrics import query_metrics
from agent.rag import retrieve_runbook 
from agent.remediation import plan_remediation, execute_remediation, AUTO_REMEDIATE_THRESHOLD
from agent.memory import recall_similar_incidents, store_incident


# ── NODE 1: Alert Ingestion ───────────────────────────────────
def ingest_alert(state: IncidentState) -> dict:
    print("\n🚨 [Node 1] Ingesting alert...")
    alert = state["alert"]
    llm = get_llm()

    prompt = f"""You are an SRE triage agent. Analyze this alert and extract structured info.

Alert payload:
{json.dumps(alert, indent=2)}

Respond ONLY with valid JSON in this exact format:
{{
  "severity": "P0|P1|P2|P3",
  "affected_services": ["service1", "service2"],
  "alert_type": "latency|error_rate|saturation|availability|custom",
  "summary": "one sentence description of the problem"
}}

Severity guide:
- P0: full outage, revenue impact, >10% error rate
- P1: partial outage, degraded, >1% error rate
- P2: elevated errors, <1% error rate, no customer impact
- P3: warning threshold, investigation needed
"""

    response = llm.invoke(prompt)

    try:
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content.strip())
    except Exception:
        parsed = {
            "severity": "P1",
            "affected_services": [alert.get("service", "unknown")],
            "alert_type": "custom",
            "summary": alert.get("title", "Unknown incident")
        }

    print(f"   Severity: {parsed['severity']} | Services: {parsed['affected_services']}")

    return {
        "severity":          parsed["severity"],
        "affected_services": parsed["affected_services"],
        "status":            "investigating",
        "needs_escalation":  parsed["severity"] == "P0",
        "retry_count":       0,
        "max_retries":       MAX_RETRIES,
        "logs":              [],
        "metrics":           [],
        "confidence_history":[],
        "similar_past_incidents": [],
    }

# agent/graph.py — ADD node: recall_memory (goes BEFORE fetch_evidence)

def recall_memory(state: IncidentState) -> dict:
    """
    First thing the agent does after triage —
    search memory for similar past incidents.
    Results get injected into the reasoning prompt.
    """
    print(f"\n🧠 [recall_memory] Searching past incidents...")

    query = " ".join([
        state["alert"].get("title", ""),
        state["alert"].get("metric", ""),
        " ".join(state.get("affected_services", [])),
    ])

    similar = recall_similar_incidents(query)

    if similar:
        best = similar[0]
        print(f"   Best match: {best['incident_id']} ({best['similarity']:.0%}) — {best['title'][:50]}")

    return {"similar_past_incidents": similar}


# ── NODE 2: Fetch Evidence (logs + metrics) ───────────────────
def fetch_evidence(state: IncidentState) -> dict:
    retry  = state.get("retry_count", 0)
    window = [15, 30, 60][min(retry, 2)]

    print(f"\n🔍 [fetch_evidence] retry={retry}, window={window}min")

    all_logs    = []
    all_metrics = []

    for service in state["affected_services"]:
        logs = query_logs(
            service=service,
            time_window_minutes=window,
            severity_filter=["ERROR", "CRITICAL", "FATAL"],
        )
        all_logs.extend(logs)

        metrics = query_metrics(
            service=service,
            time_window_minutes=window,
        )
        all_metrics.extend(metrics)

        print(f"   {service}: {len(logs)} logs, {len(metrics)} metrics")

    return {
        "logs":    all_logs,
        "metrics": all_metrics,
    }


# agent/graph.py — update analyze_root_cause

def analyze_root_cause(state: IncidentState) -> dict:
    retry = state.get("retry_count", 0)
    print(f"\n🧠 [analyze_root_cause] attempt {retry + 1}/{MAX_RETRIES}")

    result = reason(
        alert=state["alert"],
        logs=state["logs"],
        metrics=state["metrics"],
        previous_hypothesis=state.get("hypothesis", ""),
        retry_count=retry,
        similar_incidents=state.get("similar_past_incidents", []),  # ← ADD THIS
    )

    confidence = result["confidence"]
    print(f"   Hypothesis : {result['hypothesis'][:80]}...")
    print(f"   Confidence : {confidence:.0%}")

    if result["needs_more_evidence"] and retry < MAX_RETRIES - 1:
        print(f"   Missing    : {result.get('missing_evidence', 'more data')}")

    return {
        "hypothesis":         result["hypothesis"],
        "root_cause":         result["root_cause"],
        "confidence":         confidence,
        "confidence_history": [{"attempt": retry + 1, "score": confidence}],
        "retry_count":        retry + 1,
        "needs_escalation":   state.get("severity") == "P0",
    }


# ── ROUTER: Confidence Loop ───────────────────────────────────
def confidence_router(state: IncidentState):
    confidence  = state.get("confidence", 0.0)
    retry_count = state.get("retry_count", 0)

    if confidence >= CONFIDENCE_THRESHOLD:
        print(f"\n✅ Confidence {confidence:.0%} >= {CONFIDENCE_THRESHOLD:.0%} — proceeding")
        return "proceed"

    if retry_count >= MAX_RETRIES:
        print(f"\n⚠️  Max retries ({MAX_RETRIES}) reached at {confidence:.0%} — escalating")
        return "escalate"

    print(f"\n🔄 Confidence {confidence:.0%} < {CONFIDENCE_THRESHOLD:.0%} — retrying (attempt {retry_count + 1})")
    return "retry"


# ── NODE 4: Fetch Runbook ────────────────────────────────────
def fetch_runbook(state: IncidentState) -> dict:
    """
    Semantic runbook retrieval using ChromaDB RAG.
    Builds a rich query from the incident context — not just service name.
    """
    print(f"\n📖 [fetch_runbook] Querying ChromaDB...")

    # Build a rich semantic query from everything we know so far
    query = " ".join([
        state.get("hypothesis", ""),
        state.get("root_cause", ""),
        " ".join(state.get("affected_services", [])),
        state["alert"].get("metric", ""),
        state["alert"].get("title", ""),
    ]).strip()

    print(f"   Query: {query[:100]}...")

    result = retrieve_runbook(query)

    print(f"   Match: '{result['title']}' | Score: {result['relevance_score']:.0%}")

    return {
        "runbook_title":   result["title"],
        "runbook_content": result["content"],
    }

# agent/graph.py — add this new node

def auto_remediate(state: IncidentState) -> dict:
    """
    Autonomous remediation node.

    if confidence >= AUTO_REMEDIATE_THRESHOLD:
        plan → execute → verify
    else:
        skip, let page_oncall handle it
    """
    confidence = state.get("confidence", 0.0)
    print(f"\n🤖 [auto_remediate] confidence={confidence:.0%}")

    # Only auto-remediate if confidence is high enough
    if confidence < AUTO_REMEDIATE_THRESHOLD:
        print(f"   ⚠️  Confidence too low — skipping auto-remediation, escalating")
        return {
            "remediation_attempted": False,
            "remediation_result":    "Skipped — confidence below threshold",
        }

    # Plan the remediation
    plan = plan_remediation(
        root_cause=state.get("root_cause", ""),
        services=state.get("affected_services", []),
    )

    print(f"   Plan  : {plan['action']} on {plan['service']}")
    print(f"   Reason: {plan['reason']}")

    if plan["action"] == "escalate":
        print(f"   ⚠️  No rule matched — escalating to human")
        return {
            "remediation_attempted": False,
            "remediation_result":    "No matching remediation rule — escalated",
        }

    # Execute
    print(f"   Executing...")
    result = execute_remediation(plan)

    status = "Success" if result["success"] else "Failed"
    print(f"   {status}: {result['message']}")

    return {
        "remediation_attempted": True,
        "remediation_result":    f"{plan['action']} on {plan['service']}: {result['message']}",
    }

# ── NODE 5: Page On-Call ──────────────────────────────────────
def page_oncall(state: IncidentState) -> dict:
    print("\n📟 [page_oncall] Paging on-call team...")

    result = page_team(
        services=state["affected_services"],
        severity=state["severity"],
        summary=state["alert"].get("title", "Incident"),
        root_cause=state.get("root_cause", "")[:300],
    )

    print(f"   Paged: {result['team']} | PD ID: {result['incident_id']}")
    return {"team_paged": result["team"]}


# ── NODE 6: Notify Slack ──────────────────────────────────────
def notify_slack(state: IncidentState) -> dict:
    print("\n💬 [notify_slack] Posting to Slack #incidents...")

    message = f"""🚨 *{state['severity']} INCIDENT DECLARED*
*Services:* {', '.join(state['affected_services'])}
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
*On-Call:* {state.get('team_paged', 'unknown')}
*Confidence:* {state.get('confidence', 0):.0%}

*Root Cause:*
{state.get('root_cause', 'investigating...')[:300]}

*Runbook:* {state.get('runbook_title', 'N/A')}"""

    thread_url = post_slack_message(
        channel="#incidents",
        message=message,
        severity=state["severity"],
    )

    print(f"   Posted ✓ | Thread: {thread_url}")
    return {"slack_thread": thread_url}


# ── NODE 7: Create Ticket ─────────────────────────────────────
def create_ticket(state: IncidentState) -> dict:
    print("\n🎫 [create_ticket] Creating Jira ticket...")

    ticket_id = create_incident_ticket(
        severity=state["severity"],
        title=state["alert"].get("title", "Incident"),
        services=state["affected_services"],
        root_cause=state.get("root_cause", ""),
        runbook=state.get("runbook_content", ""),
        slack_thread=state.get("slack_thread", ""),
    )

    print(f"   Ticket: {ticket_id}")
    return {"ticket_id": ticket_id}


# ── NODE 8: Generate Report ───────────────────────────────────
def generate_report(state: IncidentState) -> dict:
    print("\n📋 [generate_report] Generating postmortem...")

    llm = get_llm()

    prompt = f"""Generate a structured incident postmortem report.

SEVERITY: {state['severity']}
SERVICES: {', '.join(state['affected_services'])}
TEAM PAGED: {state.get('team_paged', 'unknown')}
TICKET: {state.get('ticket_id', 'unknown')}
CONFIDENCE: {state.get('confidence', 0):.0%}
RETRIES NEEDED: {state.get('retry_count', 0)}

HYPOTHESIS:
{state.get('hypothesis', 'N/A')}

ROOT CAUSE:
{state.get('root_cause', 'N/A')}

RUNBOOK APPLIED:
{state.get('runbook_title', 'N/A')}
{state.get('runbook_content', '')[:400]}

Write a professional incident report with:
1. Executive Summary
2. Timeline
3. Root Cause
4. Impact Assessment
5. Actions Taken
6. Prevention Steps
"""

    response = llm.invoke(prompt)

    return {
        "incident_report": response.content.strip(),
        "status": "mitigating" if state["severity"] in ["P0", "P1"] else "resolved",
    }

# agent/graph.py — ADD node: save_to_memory (goes AFTER generate_report)

def save_to_memory(state: IncidentState) -> dict:
    """
    Last thing the agent does —
    store this incident so future agents can learn from it.
    """
    print(f"\n💾 [save_to_memory] Storing incident in memory...")
    store_incident(state)
    return {}

# ── BUILD GRAPH ───────────────────────────────────────────────
def build_graph():
    graph = StateGraph(IncidentState)

    graph.add_node("ingest_alert",       ingest_alert)
    graph.add_node("recall_memory",      recall_memory)      # ← NEW
    graph.add_node("fetch_evidence",     fetch_evidence)
    graph.add_node("analyze_root_cause", analyze_root_cause)
    graph.add_node("fetch_runbook",      fetch_runbook)
    graph.add_node("auto_remediate",     auto_remediate)
    graph.add_node("page_oncall",        page_oncall)
    graph.add_node("notify_slack",       notify_slack)
    graph.add_node("create_ticket",      create_ticket)
    graph.add_node("generate_report",    generate_report)
    graph.add_node("save_to_memory",     save_to_memory)     # ← NEW

    graph.set_entry_point("ingest_alert")

    graph.add_edge("ingest_alert",   "recall_memory")        # ← NEW
    graph.add_edge("recall_memory",  "fetch_evidence")       # ← NEW
    graph.add_edge("fetch_evidence", "analyze_root_cause")

    graph.add_conditional_edges(
        "analyze_root_cause",
        confidence_router,
        {
            "retry":    "fetch_evidence",
            "proceed":  "fetch_runbook",
            "escalate": "page_oncall",
        }
    )

    graph.add_edge("fetch_runbook",  "auto_remediate")
    graph.add_edge("auto_remediate", "page_oncall")
    graph.add_edge("page_oncall",    "notify_slack")
    graph.add_edge("notify_slack",   "create_ticket")
    graph.add_edge("create_ticket",  "generate_report")
    graph.add_edge("generate_report","save_to_memory")       # ← NEW
    graph.add_edge("save_to_memory",  END)                   # ← NEW

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


# ── ENTRYPOINT ────────────────────────────────────────────────
def run_incident(alert_payload: dict) -> IncidentState:
    app = build_graph()

    config = {"configurable": {"thread_id": f"incident-{datetime.now().timestamp()}"}}

    initial_state = IncidentState(
        alert=alert_payload,
        logs=[],
        metrics=[],
        runbook_title="",
        runbook_content="",
        root_cause="",
        hypothesis="",
        confidence=0.0,
        confidence_history=[],
        severity="P1",
        affected_services=[],
        team_paged="",
        slack_thread="",
        ticket_id="",
        incident_report="",
        status="investigating",
        needs_escalation=False,
        retry_count=0,
        max_retries=MAX_RETRIES,
        remediation_attempted=False,
        remediation_result="",
        similar_past_incidents=[],
    )

    return app.invoke(initial_state, config=config)


if __name__ == "__main__":
    from scripts.publish_alert import SAMPLE_ALERTS
    print("=" * 60)
    print("  INCIDENT RESPONSE AGENT — LangGraph + Ollama")
    print("=" * 60)
    result = run_incident(SAMPLE_ALERTS["P1"])
    print(f"\n✅ Done | Status: {result['status']} | Ticket: {result['ticket_id']}")
    print(f"   Confidence reached: {result['confidence']:.0%} in {result['retry_count']} attempt(s)")