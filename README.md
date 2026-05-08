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

## Project Structure

```
incident-response-agent-v2/
├── agent/
│   ├── state.py          # TypedDict — shared agent brain
│   ├── graph.py          # LangGraph — 10 nodes + confidence loop
│   ├── tools.py          # External integrations (logs, PD, Slack, Jira)
│   ├── llm.py            # Ollama setup + MockLLM
│   ├── reasoner.py       # Confidence scoring + prompt engineering
│   ├── metrics.py        # Prometheus / Grafana queries
│   ├── remediation.py    # kubectl restart / rollback / scale / cache
│   ├── rag.py            # ChromaDB runbook ingestion + retrieval
│   ├── memory.py         # ChromaDB incident memory store
│   ├── redis_queue.py    # Redis pub/sub listener (auto-reconnect)
│   └── listener.py       # Main entrypoint
├── api/
│   └── main.py           # FastAPI REST API
├── runbooks/             # Markdown runbooks (embedded into ChromaDB)
│   ├── db_connection_pool.md
│   ├── redis_connection_failure.md
│   ├── elasticsearch_rebalancing.md
│   ├── high_error_rate.md
│   └── memory_leak.md
├── infra/
│   ├── docker-compose.yml
│   └── Dockerfile
├── scripts/
│   └── publish_alert.py  # Test: push alert to Redis
├── .env.example
├── requirements.txt
├── start.sh
└── README.md
```

---

## Setup & Run

### Prerequisites
- Python 3.11+
- Redis (`brew install redis`)
- Ollama (`brew install ollama`) — optional, USE_MOCK_LLM=1 skips it

### Quick Start

```bash
# 1. Clone and install
git clone https://github.com/yourusername/incident-response-agent-v2
cd incident-response-agent-v2
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set USE_MOCK_LLM=1 for demo without Ollama

# 3. Ingest runbooks into ChromaDB
python -m agent.rag

# 4. Seed incident memory
python -m agent.memory

# 5. Start Redis
brew services start redis

# 6. Start everything (two terminals)
# Terminal 1:
uvicorn api.main:app --reload --port 8000

# Terminal 2:
python -m agent.listener
```

### Or one command
```bash
chmod +x start.sh
./start.sh
```

### Or Docker
```bash
cd infra
docker compose up --build
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Redis + memory healthcheck |
| `GET` | `/stats` | Agent performance stats |
| `POST` | `/incidents` | Trigger agent with alert payload |
| `GET` | `/incidents` | List all incidents |
| `GET` | `/incidents/{id}` | Get specific incident result |
| `POST` | `/incidents/test/P1` | Fire sample P1 alert (demo) |

**Swagger UI:** http://localhost:8000/docs

---

## LangSmith Tracing

Every agent run is fully traced — every node, every LLM call, every tool invocation.

```bash
# Add to .env:
LANGCHAIN_API_KEY=ls__your_key_here
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=incident-response-agent
```

Get a free key at https://smith.langchain.com

---

## Incidents Handled

The agent handles three real-world scenarios out of the box:

**P0 — auth-service outage**
- Redis pod OOMKilled → all logins fail
- Agent: restart Redis + auth-service

**P1 — checkout-service high error rate**
- Missing DB index after deployment → connection pool exhausted
- Agent: rollback deployment

**P2 — search latency elevated**
- Elasticsearch shard rebalancing
- Agent: monitor, self-resolves in 15 min

---

## Swapping Mocks for Real Integrations

Each tool in `agent/tools.py` has the real production implementation commented alongside the mock:

```python
# Production — one env var swap:
DATADOG_API_KEY=...       # real log queries
PAGERDUTY_API_KEY=...     # real pages
SLACK_BOT_TOKEN=...       # real Slack messages
JIRA_URL + JIRA_TOKEN=... # real tickets
PROMETHEUS_URL=...        # real metrics
```

---

## Running with Real Ollama

```bash
# Install and pull model
brew install ollama
ollama pull mistral        # recommended
# or: ollama pull llama3.1
# or: ollama pull deepseek-coder

# Start Ollama
ollama serve

# Remove mock flag from .env
USE_MOCK_LLM=   # leave empty

# Run agent
python -m agent.listener
```

---
| Capability | Why It Matters |
|---|---|
| Event-driven Redis queue | Production-grade, not a script |
| LangGraph StateGraph | Explicit state, debuggable, resumable |
| Confidence loop with retries | True agentic behavior — acts under uncertainty |
| ChromaDB RAG runbooks | Enterprise knowledge retrieval pattern |
| Incident memory | Self-improving — learns from past incidents |
| Auto-remediation (kubectl) | Autonomous SRE — doesn't just recommend, acts |
| FastAPI REST API | Deployable, integrable service |
| LangSmith tracing | Observability of the agent itself |
| Local LLM (Ollama) | No data leaves network — enterprise requirement |
| Docker Compose | One command to run entire stack |

---

## Positioning

**This is not:** an AI chatbot for DevOps questions.

**This is:** an autonomous incident reasoning system that investigates, decides, acts, and learns — reducing MTTR from 45 minutes to under 5.

---

## License

MIT
