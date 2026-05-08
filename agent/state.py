# agent/state.py  — replace your existing file with this

from typing import TypedDict, Annotated, Literal
import operator


class IncidentState(TypedDict):
    # ── Input ──────────────────────────────────
    alert: dict

    # ── Gathered evidence ──────────────────────
    logs: Annotated[list, operator.add]      # accumulates across retries
    metrics: Annotated[list, operator.add]   # NEW: Prometheus/Grafana data

    # ── Reasoning ──────────────────────────────
    root_cause: str
    confidence: float                        # NEW: 0.0 → 1.0
    confidence_history: Annotated[list, operator.add]  # NEW: track per retry
    severity: Literal["P0", "P1", "P2", "P3"]
    affected_services: list[str]
    hypothesis: str                          # NEW: current working theory

    # ── Runbook ────────────────────────────────
    runbook_title: str
    runbook_content: str

    # ── Actions taken ──────────────────────────
    remediation_attempted: bool
    remediation_result: str
    team_paged: str
    slack_thread: str
    ticket_id: str

    # ── Memory ─────────────────────────────────
    similar_past_incidents: list[dict]       # Phase 7

    # ── Output ─────────────────────────────────
    incident_report: str
    status: Literal["investigating", "mitigating", "resolved", "escalated"]

    # ── Control flow ───────────────────────────
    retry_count: int
    needs_escalation: bool
    max_retries: int                         # NEW: configurable cap