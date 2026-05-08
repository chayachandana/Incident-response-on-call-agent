# scripts/publish_alert.py
"""
Test script: publish a mock alert to Redis.
Run this in one terminal while the agent is listening in another.

Usage:
  python scripts/publish_alert.py            # default P1 alert
  python scripts/publish_alert.py --sev P0  # P0 outage
  python scripts/publish_alert.py --sev P2  # P2 warning
"""

import sys
import json
import argparse
from datetime import datetime
sys.path.append(".")

from agent.redis_queue import publish_alert

SAMPLE_ALERTS = {
    "P0": {
        "title": "auth-service complete outage — all regions",
        "service": "auth-service",
        "metric": "availability",
        "value": "0%",
        "threshold": "99.9%",
        "environment": "production",
        "triggered_at": datetime.utcnow().isoformat() + "Z",
        "tags": ["team:platform", "region:all", "tier:critical"],
        "runbook_hint": "redis_connection_failure",
    },
    "P1": {
        "title": "High error rate on checkout-service",
        "service": "checkout-service",
        "metric": "error_rate",
        "value": "8.3%",
        "threshold": "1%",
        "environment": "production",
        "triggered_at": datetime.utcnow().isoformat() + "Z",
        "tags": ["team:payments", "region:us-east-1"],
        "runbook_hint": "db_connection_pool",
    },
    "P2": {
        "title": "Search latency elevated — eu-west-1",
        "service": "search-service",
        "metric": "p99_latency_ms",
        "value": "4200",
        "threshold": "500",
        "environment": "production",
        "triggered_at": datetime.utcnow().isoformat() + "Z",
        "tags": ["team:search", "region:eu-west-1"],
        "runbook_hint": "elasticsearch_rebalancing",
    },
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sev", default="P1", choices=["P0", "P1", "P2"])
    args = parser.parse_args()

    alert = SAMPLE_ALERTS[args.sev]
    print(f"Publishing {args.sev} alert: {alert['title']}")
    publish_alert(alert)
    print("Done. Check your agent terminal for output.")