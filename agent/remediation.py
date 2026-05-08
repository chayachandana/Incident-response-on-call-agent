"""
Auto-Remediation Tools
======================
The agent calls these based on root cause + confidence score.

if confidence >= 0.92:
    result = auto_remediate(root_cause, services)
else:
    escalate()

Each tool has:
  - Mock implementation (runs immediately, no infra needed)
  - Production implementation (real kubectl / Docker SDK calls)

Production tools:
  - restart_service()      → kubectl rollout restart
  - rollback_deployment()  → kubectl rollout undo
  - scale_pods()           → kubectl scale
  - clear_cache()          → redis-cli FLUSHDB
  - run_db_migration()     → kubectl exec + psql
"""

import os
import time
import random
import subprocess
from datetime import datetime
from typing import Optional


# ── Confidence threshold for auto-remediation ──────────────
AUTO_REMEDIATE_THRESHOLD = 0.92   # below this → escalate instead


# ─────────────────────────────────────────────
# TOOL 1: Restart Service
# ─────────────────────────────────────────────

def restart_service(
    service: str,
    namespace: str = "default",
    reason: str = "",
) -> dict:
    """
    Restart a Kubernetes deployment.
    Clears all connections, forces pod recreation.
    Use for: Redis reconnect issues, memory leaks, connection pool reset.

    Production:
        result = subprocess.run([
            "kubectl", "rollout", "restart",
            f"deployment/{service}",
            "-n", namespace
        ], capture_output=True, text=True)

        # Wait for rollout to complete
        subprocess.run([
            "kubectl", "rollout", "status",
            f"deployment/{service}",
            "-n", namespace,
            "--timeout=120s"
        ], capture_output=True, text=True)

    Docker SDK alternative:
        import docker
        client = docker.from_env()
        container = client.containers.get(service)
        container.restart(timeout=30)
    """

    print(f"   🔄 restart_service({service}) — namespace={namespace}")

    if os.getenv("USE_MOCK_LLM"):
        time.sleep(0.5)   # simulate restart time
        success = random.random() > 0.1   # 90% success rate
        return {
            "action":    "restart_service",
            "service":   service,
            "namespace": namespace,
            "success":   success,
            "duration":  "23s",
            "message":   f"deployment/{service} restarted successfully" if success
                         else f"deployment/{service} restart timed out",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Production — real kubectl
    try:
        restart = subprocess.run(
            ["kubectl", "rollout", "restart", f"deployment/{service}", "-n", namespace],
            capture_output=True, text=True, timeout=30
        )

        if restart.returncode != 0:
            return {
                "action":  "restart_service",
                "service": service,
                "success": False,
                "message": restart.stderr,
            }

        # Wait for rollout
        status = subprocess.run(
            ["kubectl", "rollout", "status", f"deployment/{service}",
             "-n", namespace, "--timeout=120s"],
            capture_output=True, text=True, timeout=130
        )

        return {
            "action":    "restart_service",
            "service":   service,
            "namespace": namespace,
            "success":   status.returncode == 0,
            "message":   status.stdout.strip(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except subprocess.TimeoutExpired:
        return {"action": "restart_service", "service": service,
                "success": False, "message": "kubectl timed out"}
    except FileNotFoundError:
        return {"action": "restart_service", "service": service,
                "success": False, "message": "kubectl not found — is it installed?"}


# ─────────────────────────────────────────────
# TOOL 2: Rollback Deployment
# ─────────────────────────────────────────────

def rollback_deployment(
    service: str,
    namespace: str = "default",
    revision: Optional[int] = None,
) -> dict:
    """
    Roll back a deployment to previous version.
    Use for: issues introduced by recent deployment.

    Production:
        cmd = ["kubectl", "rollout", "undo", f"deployment/{service}", "-n", namespace]
        if revision:
            cmd += [f"--to-revision={revision}"]
        subprocess.run(cmd, capture_output=True, text=True)
    """

    revision_str = f" to revision {revision}" if revision else " to previous version"
    print(f"   ⏪ rollback_deployment({service}{revision_str})")

    if os.getenv("USE_MOCK_LLM"):
        time.sleep(0.5)
        return {
            "action":          "rollback_deployment",
            "service":         service,
            "namespace":       namespace,
            "rolled_back_to":  f"revision {revision}" if revision else "previous version",
            "success":         True,
            "message":         f"deployment/{service} rolled back successfully",
            "timestamp":       datetime.utcnow().isoformat(),
        }

    # Production
    try:
        cmd = ["kubectl", "rollout", "undo", f"deployment/{service}", "-n", namespace]
        if revision:
            cmd += [f"--to-revision={revision}"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Wait for rollout
        status = subprocess.run(
            ["kubectl", "rollout", "status", f"deployment/{service}",
             "-n", namespace, "--timeout=120s"],
            capture_output=True, text=True, timeout=130
        )

        return {
            "action":    "rollback_deployment",
            "service":   service,
            "success":   result.returncode == 0,
            "message":   result.stdout.strip() or result.stderr.strip(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"action": "rollback_deployment", "service": service,
                "success": False, "message": str(e)}


# ─────────────────────────────────────────────
# TOOL 3: Scale Pods
# ─────────────────────────────────────────────

def scale_pods(
    service: str,
    replicas: int,
    namespace: str = "default",
) -> dict:
    """
    Scale a deployment to a specific replica count.
    Use for: traffic spikes, capacity issues.

    Production:
        subprocess.run([
            "kubectl", "scale", f"deployment/{service}",
            f"--replicas={replicas}", "-n", namespace
        ])

    Kubernetes Python SDK alternative:
        from kubernetes import client, config
        config.load_kube_config()
        apps_v1 = client.AppsV1Api()
        apps_v1.patch_namespaced_deployment_scale(
            name=service, namespace=namespace,
            body={"spec": {"replicas": replicas}}
        )
    """

    print(f"   📈 scale_pods({service}, replicas={replicas})")

    if os.getenv("USE_MOCK_LLM"):
        time.sleep(0.3)
        return {
            "action":    "scale_pods",
            "service":   service,
            "replicas":  replicas,
            "success":   True,
            "message":   f"deployment/{service} scaled to {replicas} replicas",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Production
    try:
        result = subprocess.run(
            ["kubectl", "scale", f"deployment/{service}",
             f"--replicas={replicas}", "-n", namespace],
            capture_output=True, text=True, timeout=30
        )

        return {
            "action":   "scale_pods",
            "service":  service,
            "replicas": replicas,
            "success":  result.returncode == 0,
            "message":  result.stdout.strip() or result.stderr.strip(),
        }

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"action": "scale_pods", "service": service,
                "success": False, "message": str(e)}


# ─────────────────────────────────────────────
# TOOL 4: Clear Cache
# ─────────────────────────────────────────────

def clear_cache(
    service: str,
    cache_type: str = "redis",
    pattern: str = "*",
) -> dict:
    """
    Clear Redis cache for a service.
    Use for: stale cache causing errors, memory pressure.

    Production:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL"))
        if pattern == "*":
            r.flushdb()
        else:
            keys = r.keys(pattern)
            if keys:
                r.delete(*keys)
    """

    print(f"   🧹 clear_cache({service}, pattern={pattern})")

    if os.getenv("USE_MOCK_LLM"):
        time.sleep(0.2)
        keys_cleared = random.randint(100, 50000)
        return {
            "action":       "clear_cache",
            "service":      service,
            "cache_type":   cache_type,
            "keys_cleared": keys_cleared,
            "success":      True,
            "message":      f"Cleared {keys_cleared} keys from {cache_type}",
            "timestamp":    datetime.utcnow().isoformat(),
        }

    # Production
    try:
        import redis as redis_client
        r = redis_client.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        if pattern == "*":
            r.flushdb()
            return {"action": "clear_cache", "service": service,
                    "success": True, "message": "Cache flushed"}
        else:
            keys = r.keys(pattern)
            if keys:
                r.delete(*keys)
            return {"action": "clear_cache", "service": service,
                    "success": True, "message": f"Cleared {len(keys)} keys"}
    except Exception as e:
        return {"action": "clear_cache", "service": service,
                "success": False, "message": str(e)}


# ─────────────────────────────────────────────
# REMEDIATION PLANNER
# ─────────────────────────────────────────────

# Maps root cause keywords → remediation action
REMEDIATION_RULES = [
    {
        "keywords":  ["connection pool", "pool exhausted", "pool timeout"],
        "action":    "rollback_deployment",
        "reason":    "Pool exhaustion usually caused by bad deploy — rollback first",
        "fallback":  "restart_service",
    },
    {
        "keywords":  ["redis", "econnrefused", "session store", "cache"],
        "action":    "restart_service",
        "target":    "redis",
        "reason":    "Redis connection failure — restart Redis pod",
    },
    {
        "keywords":  ["memory", "oom", "oomkilled", "heap"],
        "action":    "restart_service",
        "reason":    "Memory leak — restart buys time, then investigate",
    },
    {
        "keywords":  ["traffic", "spike", "capacity", "overload", "saturation"],
        "action":    "scale_pods",
        "replicas":  6,
        "reason":    "Traffic spike — scale out immediately",
    },
    {
        "keywords":  ["deployment", "deploy", "version", "rollout", "release"],
        "action":    "rollback_deployment",
        "reason":    "Issue correlates with recent deployment",
    },
    {
        "keywords":  ["cache", "stale", "evict"],
        "action":    "clear_cache",
        "reason":    "Cache corruption or memory pressure",
    },
]


def plan_remediation(root_cause: str, services: list) -> dict:
    """
    Match root cause to the best remediation action.
    Returns the plan — does NOT execute it yet.
    """
    root_lower = root_cause.lower()

    for rule in REMEDIATION_RULES:
        if any(kw in root_lower for kw in rule["keywords"]):
            return {
                "action":   rule["action"],
                "service":  rule.get("target", services[0] if services else "unknown"),
                "reason":   rule["reason"],
                "replicas": rule.get("replicas", 4),
                "matched":  True,
            }

    # No rule matched
    return {
        "action":  "escalate",
        "service": services[0] if services else "unknown",
        "reason":  "No automated remediation rule matched — escalating to human",
        "matched": False,
    }


def execute_remediation(plan: dict) -> dict:
    """
    Execute the remediation plan and return the result.
    """
    action  = plan["action"]
    service = plan["service"]

    if action == "restart_service":
        return restart_service(service, reason=plan.get("reason", ""))

    elif action == "rollback_deployment":
        return rollback_deployment(service)

    elif action == "scale_pods":
        return scale_pods(service, replicas=plan.get("replicas", 4))

    elif action == "clear_cache":
        return clear_cache(service)

    else:
        return {
            "action":  "escalate",
            "service": service,
            "success": False,
            "message": plan.get("reason", "Manual intervention required"),
        }