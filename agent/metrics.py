"""
Metrics querying tool — Prometheus / Grafana / Datadog
=======================================================
Queries time-series metrics for a service to support
root cause analysis alongside log evidence.

Production swap:
  Replace _mock_metrics() body with real Prometheus API calls.
  Prometheus HTTP API is dead simple:
    GET /api/v1/query_range?query=...&start=...&end=...&step=...
"""

import os
import random
from datetime import datetime, timedelta


#  Prometheus query templates 
PROMETHEUS_QUERIES = {
    "error_rate": 'rate(http_requests_total{{service="{svc}",status=~"5.."}}[5m])',
    "latency_p99": 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{svc}"}}[5m]))',
    "cpu_usage":   'rate(container_cpu_usage_seconds_total{{service="{svc}"}}[5m])',
    "memory_mb":   'container_memory_usage_bytes{{service="{svc}"}} / 1024 / 1024',
    "db_pool_used":'db_connection_pool_active{{service="{svc}"}}',
    "db_pool_max": 'db_connection_pool_max{{service="{svc}"}}',
    "request_rate":'rate(http_requests_total{{service="{svc}"}}[1m])',
}


def query_metrics(
    service: str,
    time_window_minutes: int = 15,
) -> list[dict]:
    """
    Query key metrics for a service over a time window.

    Production implementation:
        import requests
        PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

        end = datetime.utcnow()
        start = end - timedelta(minutes=time_window_minutes)

        results = []
        for metric_name, query_template in PROMETHEUS_QUERIES.items():
            query = query_template.format(svc=service)
            resp = requests.get(
                f"{PROMETHEUS_URL}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.timestamp(),
                    "end":   end.timestamp(),
                    "step":  "60",   # 1 min resolution
                },
                timeout=10,
            )
            data = resp.json()
            if data["status"] == "success" and data["data"]["result"]:
                values = data["data"]["result"][0]["values"]
                # values = [[timestamp, "value"], ...]
                latest = float(values[-1][1])
                results.append({
                    "metric": metric_name,
                    "service": service,
                    "latest_value": latest,
                    "unit": _units[metric_name],
                    "anomaly": _is_anomalous(metric_name, latest),
                    "time_window_minutes": time_window_minutes,
                })
        return results
    """

    return _mock_metrics(service, time_window_minutes)


def _is_anomalous(metric: str, value: float) -> bool:
    """Simple threshold-based anomaly detection."""
    thresholds = {
        "error_rate":    0.01,   # >1% = anomalous
        "latency_p99":   1.0,    # >1s p99 = anomalous
        "cpu_usage":     0.85,   # >85% = anomalous
        "db_pool_used":  40,     # >40 connections = anomalous (if max=50)
    }
    return value > thresholds.get(metric, float("inf"))


_units = {
    "error_rate":    "req/s errors",
    "latency_p99":   "seconds",
    "cpu_usage":     "cores",
    "memory_mb":     "MB",
    "db_pool_used":  "connections",
    "db_pool_max":   "connections",
    "request_rate":  "req/s",
}


# ── Service-specific mock profiles ─────────────────────────

_METRIC_PROFILES = {
    "checkout-service": {
        "error_rate":   (0.08, 0.02),   # (mean, stddev) — elevated
        "latency_p99":  (4.2,  0.8),    # high latency
        "cpu_usage":    (0.45, 0.05),   # normal
        "memory_mb":    (380,  20),     # normal
        "db_pool_used": (48,   2),      # NEAR MAX — anomalous
        "db_pool_max":  (50,   0),
        "request_rate": (120,  15),
    },
    "auth-service": {
        "error_rate":   (0.99, 0.01),   # total failure
        "latency_p99":  (30.0, 5.0),    # timeouts
        "cpu_usage":    (0.05, 0.01),   # low — not computing, just failing
        "memory_mb":    (110,  5),
        "db_pool_used": (0,    0),      # not even reaching DB
        "db_pool_max":  (50,   0),
        "request_rate": (200,  20),
    },
    "search-service": {
        "error_rate":   (0.005, 0.002),
        "latency_p99":  (4.2,   0.5),   # high latency
        "cpu_usage":    (0.72,  0.1),   # elevated
        "memory_mb":    (720,   50),    # elevated
        "db_pool_used": (12,    3),     # normal
        "db_pool_max":  (50,    0),
        "request_rate": (85,    10),
    },
}

_DEFAULT_PROFILE = {
    "error_rate":   (0.01, 0.005),
    "latency_p99":  (0.3,  0.05),
    "cpu_usage":    (0.3,  0.05),
    "memory_mb":    (256,  30),
    "db_pool_used": (10,   3),
    "db_pool_max":  (50,   0),
    "request_rate": (100,  10),
}


def _mock_metrics(service: str, window: int) -> list[dict]:
    """Generate realistic mock metrics based on service profile."""
    profile = _METRIC_PROFILES.get(service, _DEFAULT_PROFILE)
    results = []

    for metric_name, (mean, std) in profile.items():
        value = max(0, random.gauss(mean, std))
        results.append({
            "metric":              metric_name,
            "service":             service,
            "latest_value":        round(value, 4),
            "unit":                _units.get(metric_name, ""),
            "anomaly":             _is_anomalous(metric_name, value),
            "time_window_minutes": window,
        })

    return results