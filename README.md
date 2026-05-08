## Incident-response-on-call-agent


> **Autonomous SRE agent that reduces MTTR from 45 minutes to under 5.**
> Built with LangGraph · Ollama (local LLM) · ChromaDB · Redis · FastAPI

---

## What This Project Does

Modern distributed systems generate thousands of alerts daily. When something breaks at 3am, an engineer gets woken up and spends 45 minutes:
- Digging through logs manually
- Checking dashboards
- Finding the right runbook
- Figuring out what to do
- Paging the right team
- Writing up the incident

**This agent does all of that automatically — in under 5 minutes — with no human required.**

---
## Demo

```bash
# Start everything
./start.sh

# Fire a P1 incident
curl -X POST http://localhost:8000/incidents/test/P1

# Watch the agent work in Terminal 1:
# 🚨 [ingest_alert]       Severity: P1 | Services: checkout-service
# 🧠 [recall_memory]      Found INC-2831 (89% match) — same issue 2 weeks ago
# 🔍 [fetch_evidence]     12 logs, 7 metrics fetched
# 🧠 [analyze_root_cause] Confidence: 94% — DB pool exhaustion
# ✅  Confidence >= 92% — proceeding
# 📖 [fetch_runbook]      Matched: DB Connection Pool Exhaustion (91%)
# 🤖 [auto_remediate]     Rolling back checkout-service deployment
# ✅  Rollback successful
# 📟 [page_oncall]        Paged: payments-oncall
# 💬 [notify_slack]       Posted to #incidents
# 🎫 [create_ticket]      Created: INC-3847
# 📋 [generate_report]    Postmortem written
# 💾 [save_to_memory]     Stored for future recall
```

**Open Swagger UI:** http://localhost:8000/docs

---

## Architecture

```
Alert Sources (PagerDuty / Datadog / API / CLI)
                    ↓
           Redis pub/sub queue
                    ↓
    ┌───────────────────────────────┐
    │        LangGraph Agent        │
    │                               │
    │  1. ingest_alert              │
    │     classify P0/P1/P2/P3      │
    │                               │
    │  2. recall_memory             │◄──── ChromaDB (past incidents)
    │     find similar past events  │
    │                               │
    │  3. fetch_evidence            │
    │     logs + Prometheus metrics │
    │                               │
    │  4. analyze_root_cause        │◄──── Ollama (mistral — local LLM)
    │     confidence loop:          │
    │     while confidence < 0.92:  │
    │       re-fetch wider window   │
    │       re-reason               │
    │                               │
    │  5. fetch_runbook             │◄──── ChromaDB (runbook RAG)
    │     semantic search           │
    │                               │
    │  6. auto_remediate            │
    │     if confidence >= 0.92:    │
    │       kubectl restart/rollback│
    │       scale pods / clear cache│
    │                               │
    │  7. page_oncall    (PagerDuty)│
    │  8. notify_slack   (#incidents│
    │  9. create_ticket  (Jira)     │
    │  10. generate_report          │
    │  11. save_to_memory           │◄──── ChromaDB (stores for future)
    └───────────────────────────────┘
                    ↓
    FastAPI REST API  ·  LangSmith Traces
```

---

## Key Features

### 1. Event-Driven Architecture
Alerts arrive via Redis pub/sub — the agent subscribes and fires automatically. No polling, no manual triggers in production.

### 2. Confidence-Based Reasoning Loop
```python
while confidence < 0.92:
    logs = query_logs(window=wider_each_retry)
    metrics = query_prometheus()
    hypothesis = ollama_reason(logs, metrics, past_incidents)
    confidence = hypothesis["confidence"]

if confidence >= 0.92:
    auto_remediate()
else:
    escalate_to_human()
```
The agent never acts when it's uncertain. It keeps gathering evidence until confident or escalates.

### 3. RAG Runbook Retrieval
All runbooks are stored as markdown files, embedded into ChromaDB using `sentence-transformers`. When an incident happens, the agent does semantic search — not keyword matching — to find the most relevant playbook.

### 4. Incident Memory
Every resolved incident is stored in a separate ChromaDB collection. When a new incident arrives, the agent recalls similar past events and injects them into its reasoning prompt — getting faster and more accurate over time.

### 5. Auto-Remediation
```python
if confidence >= 0.92 and rule_matched:
    restart_service()      # kubectl rollout restart
    rollback_deployment()  # kubectl rollout undo
    scale_pods(replicas=6) # kubectl scale
    clear_cache()          # redis-cli FLUSHDB
```
Real `kubectl` calls — not simulated. In mock mode they return realistic responses.

### 6. Runs Fully Local
Uses Ollama to run Mistral locally — no OpenAI API key, no data leaving your network, zero cost at scale. Critical for enterprise use cases where logs and incidents contain sensitive data.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph (StateGraph) |
| Local LLM | Ollama — Mistral / Llama 3.1 / DeepSeek |
| Vector DB | ChromaDB + sentence-transformers |
| Queue | Redis pub/sub |
| API | FastAPI + Uvicorn |
| Observability | LangSmith |
| Infra | Docker Compose |
| Remediation | kubectl + Docker SDK |

---
