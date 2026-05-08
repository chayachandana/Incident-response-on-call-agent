# agent/tools.py
"""
Tool Definitions
================
Each tool wraps a real external integration.
In demo mode, all return realistic mock data.

Tools:
  - query_logs             → Datadog / CloudWatch / Loki
  - lookup_runbook         → keyword match (Phase 5 replaces with ChromaDB)
  - page_team              → PagerDuty API
  - post_slack_message     → Slack Bolt API
  - create_incident_ticket → Jira / Linear API
"""

import os
import random
import string
from datetime import datetime, timedelta
from typing import Optional


# ─────────────────────────────────────────────
# TOOL 1: Query Logs
# ─────────────────────────────────────────────

def query_logs(
    service: str,
    time_window_minutes: int = 15,
    severity_filter: list = None,
    limit: int = 50,
) -> list:
    """
    Query error logs for a service within a time window.

    Production swap — Datadog example:
        from datadog_api_client import ApiClient, Configuration
        from datadog_api_client.v2.api.logs_api import LogsApi
        ...

    Production swap — CloudWatch Logs Insights:
        client.start_query(
            logGroupName=f'/aws/ecs/{service}',
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString='filter @message like /ERROR/ | sort @timestamp desc'
        )
    """
    return _mock_logs(service, time_window_minutes, severity_filter or ["ERROR"])


def _mock_logs(service: str, window: int, severities: list) -> list:
    """Generate realistic mock log entries per service."""
    now = datetime.utcnow()

    error_patterns = {
        "checkout-service": [
            "connection pool timeout after 30000ms waiting for connection",
            "DB query exceeded 10000ms: SELECT * FROM orders WHERE user_id=?",
            "upstream dependency payment-gateway returned 503 Service Unavailable",
            "Maximum pool size reached, rejecting connection request",
            "OOMKilled: container exceeded memory limit 512Mi",
        ],
        "payment-gateway": [
            "upstream checkout-service returned 503",
            "Circuit breaker OPEN for checkout-service after 5 failures",
            "Stripe webhook delivery failed: connection refused",
            "Transaction rollback: deadlock detected on payments table",
        ],
        "auth-service": [
            "Redis connection refused: ECONNREFUSED 127.0.0.1:6379",
            "JWT verification failed: token expired",
            "Rate limit exceeded for IP 203.0.113.42",
            "Session store unavailable — all auth failing",
        ],
        "api-gateway": [
            "Upstream timeout: checkout-service did not respond in 5000ms",
            "Connection pool exhausted for checkout-service cluster",
        ],
        "search-service": [
            "ES query took 3200ms — expected < 200ms",
            "Search timeout: request_timeout[5s] exceeded",
            "Cluster health: YELLOW — shards relocating",
        ],
    }

    patterns = error_patterns.get(service, [
        f"Unexpected error in {service}: null pointer exception",
        f"Service {service} health check failed",
    ])

    logs = []
    base_time = now - timedelta(minutes=window - 1)

    for i in range(random.randint(8, 20)):
        offset = random.uniform(0, window * 60)
        timestamp = base_time + timedelta(seconds=offset)

        logs.append({
            "timestamp": timestamp.strftime("%H:%M:%S"),
            "service":   service,
            "level":     random.choice(severities),
            "message":   random.choice(patterns),
            "trace_id":  "".join(random.choices(string.hexdigits, k=16)),
            "host":      f"{service}-pod-{random.randint(1, 8)}",
        })

    return sorted(logs, key=lambda x: x["timestamp"])


# ─────────────────────────────────────────────
# TOOL 2: Lookup Runbook
# ─────────────────────────────────────────────

def lookup_runbook(
    affected_services: list,
    root_cause_summary: str,
) -> dict:
    """
    Find the most relevant runbook for this incident.
    Phase 5 replaces this with ChromaDB semantic search.

    Production: Use a vector DB (Chroma/Pinecone) loaded with runbooks:
        from chromadb import Client
        collection = client.get_collection("runbooks")
        results = collection.query(query_texts=[root_cause_summary], n_results=1)
    """

    runbooks = {
        "db_connection_pool": {
            "title": "Database Connection Pool Exhaustion",
            "keywords": ["connection pool", "timeout", "db", "pool exhausted", "pool size"],
            "content": """# Runbook: DB Connection Pool Exhaustion

## Symptoms
- Service logs show "connection pool timeout"
- DB CPU normal but connections at max
- Latency spike on DB-dependent endpoints

## Immediate Mitigation (< 5 min)
1. Check current pool utilization:
   kubectl exec -it <pod> -- curl localhost:8080/metrics | grep db_pool
2. Temporarily increase pool size:
   kubectl set env deployment/<service> DB_POOL_SIZE=100
3. If no improvement in 2 min, rollback:
   kubectl rollout undo deployment/<service>

## Root Cause Investigation
- Check for missing indexes: EXPLAIN ANALYZE <slow query>
- Review recent deployments: kubectl rollout history deployment/<service>
- Check for N+1 queries in APM traces

## Escalation
If rollback doesn't resolve within 10 min: page #team-platform-eng""",
        },
        "redis_failure": {
            "title": "Redis Connection Failure",
            "keywords": ["redis", "econnrefused", "session", "cache", "6379"],
            "content": """# Runbook: Redis Connection Failure

## Symptoms
- ECONNREFUSED on Redis port 6379
- Auth/session failures across services
- Low CPU but 100% error rate

## Immediate Mitigation
1. Check Redis pod: kubectl get pods -n cache | grep redis
2. Restart Redis: kubectl rollout restart deployment/redis
3. Force service reconnect: kubectl rollout restart deployment/<service>

## Escalation
Page: platform-oncall — this is typically P0""",
        },
        "high_error_rate": {
            "title": "High Error Rate — General",
            "keywords": ["error rate", "503", "5xx", "upstream", "failure"],
            "content": """# Runbook: High Error Rate

## Immediate Steps
1. Check deployment history for recent changes
2. Review error logs for common pattern
3. Check upstream dependencies health
4. Assess if rollback is safe and warranted

## Decision Tree
- After deployment → rollback
- Traffic spike → scale pods
- DB issues → check db_connection_pool runbook
- Redis issues → check redis_failure runbook

## Escalation
Page: team owning the affected service""",
        },
        "elasticsearch": {
            "title": "Elasticsearch Shard Rebalancing",
            "keywords": ["elasticsearch", "elastic", "search", "shard", "yellow", "latency"],
            "content": """# Runbook: Elasticsearch Shard Rebalancing

## Symptoms
- Search latency elevated (p99 > 2s)
- ES cluster health YELLOW
- Logs: shards relocating

## Immediate Mitigation
1. Check cluster health: curl localhost:9200/_cluster/health?pretty
2. Usually self-resolving in 10-15 min — monitor first
3. To speed up: increase concurrent rebalance setting
4. To pause rebalancing temporarily:
   PUT /_cluster/settings {"transient": {"cluster.routing.rebalance.enable": "none"}}

## Escalation
Page: search-oncall""",
        },
    }

    # Keyword matching (Phase 5 replaces with semantic similarity)
    search_text = (root_cause_summary + " " + " ".join(affected_services)).lower()
    best_match = None
    best_score = 0

    for key, runbook in runbooks.items():
        score = sum(1 for kw in runbook["keywords"] if kw in search_text)
        if score > best_score:
            best_score = score
            best_match = runbook

    return best_match or runbooks["high_error_rate"]


# ─────────────────────────────────────────────
# TOOL 3: Page On-Call Team
# ─────────────────────────────────────────────

def page_team(
    services: list,
    severity: str,
    summary: str,
    root_cause: str,
) -> dict:
    """
    Page the on-call engineer via PagerDuty.

    Production swap:
        import pdpyras
        session = pdpyras.APISession(os.getenv("PAGERDUTY_API_KEY"))
        session.rpost("incidents", json={
            "incident": {
                "type": "incident",
                "title": summary,
                "service": {"id": SERVICE_ID_MAP[services[0]], "type": "service_reference"},
                "urgency": "high" if severity in ["P0", "P1"] else "low",
                "body": {"type": "incident_body", "details": root_cause},
            }
        })
    """

    team_map = {
        "checkout-service":  "payments-oncall",
        "payment-gateway":   "payments-oncall",
        "auth-service":      "platform-oncall",
        "api-gateway":       "platform-oncall",
        "user-service":      "identity-oncall",
        "search-service":    "search-oncall",
    }

    team = team_map.get(services[0] if services else "unknown", "platform-oncall")
    incident_id = "PD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

    print(f"   📟 PagerDuty: Paging {team} | Incident {incident_id}")

    return {
        "team":              team,
        "incident_id":       incident_id,
        "status":            "triggered",
        "escalation_policy": f"{team}-policy",
    }


# ─────────────────────────────────────────────
# TOOL 4: Post Slack Message
# ─────────────────────────────────────────────

def post_slack_message(
    channel: str,
    message: str,
    severity: str,
    thread_ts: Optional[str] = None,
) -> str:
    """
    Post to Slack and return thread URL.

    Production swap:
        from slack_bolt import App
        app = App(token=os.getenv("SLACK_BOT_TOKEN"))
        result = app.client.chat_postMessage(
            channel=channel,
            text=message,
            thread_ts=thread_ts,
        )
        return f"https://slack.com/archives/{result['channel']}/p{result['ts'].replace('.','')}"
    """

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    thread_url = f"https://acme.slack.com/archives/C0INCIDENTS/p{ts}"

    print(f"   💬 Slack: Posted to {channel}")
    return thread_url


# ─────────────────────────────────────────────
# TOOL 5: Create Incident Ticket
# ─────────────────────────────────────────────

def create_incident_ticket(
    severity: str,
    title: str,
    services: list,
    root_cause: str,
    runbook: str,
    slack_thread: str,
) -> str:
    """
    Create a Jira or Linear ticket.

    Production swap (Jira):
        from jira import JIRA
        jira = JIRA(server=os.getenv("JIRA_URL"), token_auth=os.getenv("JIRA_TOKEN"))
        issue = jira.create_issue(
            project="INC",
            summary=f"[{severity}] {title}",
            description=f"*Root Cause:*\n{root_cause}\n\n*Slack:* {slack_thread}",
            issuetype={"name": "Incident"},
            priority={"name": PRIORITY_MAP[severity]},
        )
        return issue.key
    """

    priority_map = {"P0": "Critical", "P1": "High", "P2": "Medium", "P3": "Low"}
    ticket_id = f"INC-{random.randint(1000, 9999)}"

    print(f"   🎫 Jira: Created {ticket_id} ({priority_map.get(severity, 'High')} priority)")
    return ticket_id