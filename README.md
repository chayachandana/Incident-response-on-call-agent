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