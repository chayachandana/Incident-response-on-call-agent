# api/main.py
"""
FastAPI — Incident Response Agent API
======================================
Endpoints:
  POST /incidents          → trigger agent with alert payload
  GET  /incidents          → list all past incidents from memory
  GET  /incidents/{id}     → get specific incident
  GET  /health             → healthcheck
  GET  /metrics            → agent performance stats
  POST /incidents/test     → fire a sample alert (demo endpoint)

Run:
  uvicorn api.main:app --reload --port 8000
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from agent.graph import run_incident
from agent.redis_queue import publish_alert
from agent.memory import recall_similar_incidents, _get_collection


# ── App setup ──────────────────────────────────────────────
app = FastAPI(
    title="Incident Response Agent",
    description="Autonomous SRE agent — LangGraph + Ollama + ChromaDB",
    version="2.0.0",
    docs_url="/docs",     # Swagger UI at localhost:8000/docs
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for active incidents (swap for Redis/DB in production)
active_incidents: dict = {}


# ── Request / Response models ───────────────────────────────

class AlertPayload(BaseModel):
    title: str
    service: str
    metric: str
    value: str
    threshold: str
    environment: str = "production"
    tags: list[str] = []
    runbook_hint: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "title": "High error rate on checkout-service",
                "service": "checkout-service",
                "metric": "error_rate",
                "value": "8.3%",
                "threshold": "1%",
                "environment": "production",
                "tags": ["team:payments", "region:us-east-1"],
            }
        }


class IncidentResponse(BaseModel):
    incident_id: str
    status: str
    severity: str
    affected_services: list[str]
    root_cause: str
    confidence: float
    team_paged: str
    ticket_id: str
    slack_thread: str
    remediation_result: str
    triggered_at: str


class HealthResponse(BaseModel):
    status: str
    redis: str
    memory_incidents: int
    version: str
    timestamp: str


# ── Helper: run agent in background ────────────────────────

def _run_agent_background(alert: dict, incident_id: str):
    """Run the agent and store result in active_incidents."""
    try:
        active_incidents[incident_id] = {
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        }

        result = run_incident(alert)

        active_incidents[incident_id] = {
            "status":             "complete",
            "incident_id":        result.get("ticket_id", incident_id),
            "severity":           result.get("severity", "unknown"),
            "affected_services":  result.get("affected_services", []),
            "root_cause":         result.get("root_cause", ""),
            "confidence":         result.get("confidence", 0.0),
            "team_paged":         result.get("team_paged", ""),
            "ticket_id":          result.get("ticket_id", ""),
            "slack_thread":       result.get("slack_thread", ""),
            "remediation_result": result.get("remediation_result", ""),
            "incident_report":    result.get("incident_report", ""),
            "triggered_at":       datetime.utcnow().isoformat(),
        }

    except Exception as e:
        active_incidents[incident_id] = {
            "status": "error",
            "error":  str(e),
        }


# ── ROUTES ──────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Healthcheck — verify Redis and memory are reachable."""

    # Check Redis
    redis_status = "ok"
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        r.ping()
    except Exception as e:
        redis_status = f"error: {e}"

    # Check memory
    memory_count = 0
    try:
        col = _get_collection()
        memory_count = col.count()
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if redis_status == "ok" else "degraded",
        redis=redis_status,
        memory_incidents=memory_count,
        version="2.0.0",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/incidents", tags=["Incidents"])
async def trigger_incident(
    alert: AlertPayload,
    background_tasks: BackgroundTasks,
):
    """
    Trigger the incident response agent with an alert payload.
    Agent runs in background — returns immediately with tracking ID.

    Poll GET /incidents/{id} for results.
    """
    incident_id = f"INC-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    alert_dict = alert.dict()
    alert_dict["triggered_at"] = datetime.utcnow().isoformat() + "Z"

    # Run agent in background thread
    background_tasks.add_task(
        _run_agent_background,
        alert_dict,
        incident_id,
    )

    # Also publish to Redis queue (triggers listener if running)
    try:
        publish_alert(alert_dict)
    except Exception:
        pass  # Redis optional — agent runs directly via background task

    return {
        "incident_id": incident_id,
        "status":      "triggered",
        "message":     "Agent activated. Poll /incidents/{id} for results.",
        "poll_url":    f"/incidents/{incident_id}",
        "triggered_at": datetime.utcnow().isoformat(),
    }


@app.get("/incidents/{incident_id}", tags=["Incidents"])
async def get_incident(incident_id: str):
    """Get the status and result of a specific incident."""

    if incident_id not in active_incidents:
        # Check memory for past incidents
        similar = recall_similar_incidents(incident_id, limit=1)
        if similar:
            return similar[0]
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    return active_incidents[incident_id]


@app.get("/incidents", tags=["Incidents"])
async def list_incidents(limit: int = 10):
    """List all incidents — active + past from memory."""

    # Active/recent incidents
    recent = list(active_incidents.values())[-limit:]

    # Past incidents from memory
    try:
        col = _get_collection()
        if col.count() > 0:
            stored = col.get(include=["metadatas"])
            past = [
                {
                    "incident_id": m.get("incident_id"),
                    "title":       m.get("title"),
                    "severity":    m.get("severity"),
                    "occurred_at": m.get("occurred_at"),
                    "root_cause":  m.get("root_cause", "")[:100] + "...",
                    "resolution":  m.get("resolution", "")[:100],
                    "source":      "memory",
                }
                for m in stored["metadatas"]
            ]
        else:
            past = []
    except Exception:
        past = []

    return {
        "active":       recent,
        "past":         past,
        "total_active": len(active_incidents),
        "total_memory": len(past),
    }


@app.post("/incidents/test/{severity}", tags=["Demo"])
async def fire_test_alert(
    severity: str,
    background_tasks: BackgroundTasks,
):
    """
    Fire a sample alert for demo purposes.
    severity: P0, P1, P2
    """
    samples = {
        "P0": AlertPayload(
            title="auth-service complete outage — all regions",
            service="auth-service",
            metric="availability",
            value="0%",
            threshold="99.9%",
            tags=["team:platform", "region:all"],
        ),
        "P1": AlertPayload(
            title="High error rate on checkout-service",
            service="checkout-service",
            metric="error_rate",
            value="8.3%",
            threshold="1%",
            tags=["team:payments", "region:us-east-1"],
        ),
        "P2": AlertPayload(
            title="Search latency elevated — eu-west-1",
            service="search-service",
            metric="p99_latency_ms",
            value="4200",
            threshold="500",
            tags=["team:search", "region:eu-west-1"],
        ),
    }

    if severity.upper() not in samples:
        raise HTTPException(status_code=400, detail="severity must be P0, P1, or P2")

    return await trigger_incident(samples[severity.upper()], background_tasks)


@app.get("/stats", tags=["System"])
async def get_stats():
    """Agent performance statistics."""
    try:
        col = _get_collection()
        total = col.count()

        severities = {}
        avg_confidence = 0.0

        if total > 0:
            stored = col.get(include=["metadatas"])
            for m in stored["metadatas"]:
                sev = m.get("severity", "unknown")
                severities[sev] = severities.get(sev, 0) + 1
                try:
                    avg_confidence += float(m.get("confidence", 0))
                except Exception:
                    pass
            avg_confidence = round(avg_confidence / total, 3)

        return {
            "total_incidents_resolved": total,
            "by_severity":              severities,
            "avg_confidence":           avg_confidence,
            "active_incidents":         len(active_incidents),
            "agent_version":            "2.0.0",
        }
    except Exception as e:
        return {"error": str(e)}