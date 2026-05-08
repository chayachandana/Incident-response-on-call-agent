"""
Incident Memory — ChromaDB
==========================
Two responsibilities:

1. recall_similar_incidents(query)
   → semantic search over past incidents
   → called at START of each new incident
   → results injected into root cause reasoning

2. store_incident(state)
   → called at END of each resolved incident
   → embeds the postmortem into ChromaDB
   → future incidents can learn from this one

Storage: separate ChromaDB collection from runbooks
         persists to disk at .chromadb_memory/
"""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions


MEMORY_DB_PATH    = os.getenv("MEMORY_DB_PATH", ".chromadb_memory")
COLLECTION_NAME   = "incident_memory"
EMBEDDING_MODEL   = "all-MiniLM-L6-v2"   # same model as runbooks
MAX_RESULTS       = 3                     # how many past incidents to recall


def _get_collection():
    """Get or create the incident memory ChromaDB collection."""
    client = chromadb.PersistentClient(path=MEMORY_DB_PATH)

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )


def recall_similar_incidents(
    query: str,
    min_score: float = 0.5,
    limit: int = MAX_RESULTS,
) -> list[dict]:
    """
    Search past incidents semantically.

    Args:
        query: description of current incident
               built from: alert title + affected services + initial hypothesis
        min_score: minimum similarity (0-1). 0.5 = somewhat similar
        limit: max incidents to return

    Returns list of past incidents, most similar first:
        [{
            "incident_id":   "INC-3821",
            "title":         "High error rate on checkout-service",
            "root_cause":    "Missing index on orders table...",
            "resolution":    "Rolled back to v2.3.1",
            "severity":      "P1",
            "services":      ["checkout-service"],
            "occurred_at":   "2026-04-21T14:23:00",
            "similarity":    0.87,
        }]
    """
    collection = _get_collection()

    if collection.count() == 0:
        print("[memory] No past incidents stored yet")
        return []

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(limit, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        print(f"[memory] Query error: {e}")
        return []

    if not results["ids"][0]:
        return []

    similar = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similarity = round(1 - dist, 4)

        if similarity < min_score:
            continue

        similar.append({
            "incident_id":  meta.get("incident_id", "unknown"),
            "title":        meta.get("title", ""),
            "root_cause":   meta.get("root_cause", ""),
            "resolution":   meta.get("resolution", ""),
            "severity":     meta.get("severity", ""),
            "services":     json.loads(meta.get("services", "[]")),
            "occurred_at":  meta.get("occurred_at", ""),
            "duration_min": meta.get("duration_min", "unknown"),
            "similarity":   similarity,
        })

    if similar:
        print(f"[memory] Found {len(similar)} similar past incident(s)")
        for inc in similar:
            print(f"   {inc['incident_id']} ({inc['similarity']:.0%} match): {inc['title'][:60]}")
    else:
        print("[memory] No similar past incidents found")

    return similar


def store_incident(state: dict) -> str:
    """
    Store a resolved incident in memory for future recall.
    Called after generate_report completes.

    Returns the incident_id stored.
    """
    collection = _get_collection()

    incident_id = state.get("ticket_id") or f"INC-{uuid.uuid4().hex[:6].upper()}"


    document = _build_memory_document(state)

    # Metadata stored alongside the embedding for filtering and display during recall
    metadata = {
        "incident_id":  incident_id,
        "title":        state.get("alert", {}).get("title", "")[:200],
        "root_cause":   state.get("root_cause", "")[:500],
        "resolution":   state.get("remediation_result", "manual resolution")[:300],
        "severity":     state.get("severity", "P1"),
        "services":     json.dumps(state.get("affected_services", [])),
        "occurred_at":  datetime.utcnow().isoformat(),
        "duration_min": _estimate_duration(state),
        "confidence":   str(round(state.get("confidence", 0.0), 3)),
        "runbook_used": state.get("runbook_title", "")[:100],
    }

    try:
        collection.upsert(
            ids=[incident_id],
            documents=[document],
            metadatas=[metadata],
        )
        print(f"[memory]  Stored incident {incident_id} in memory")
        print(f"         Total incidents in memory: {collection.count()}")
        return incident_id

    except Exception as e:
        print(f"[memory]  Failed to store incident: {e}")
        return incident_id


def _build_memory_document(state: dict) -> str:
    """
    Build a rich text document from incident state.
    This text gets embedded — richer = better recall.
    """
    alert    = state.get("alert", {})
    services = ", ".join(state.get("affected_services", []))

    return f"""
Incident: {alert.get("title", "")}
Severity: {state.get("severity", "")}
Services: {services}
Alert metric: {alert.get("metric", "")} = {alert.get("value", "")}

Root Cause:
{state.get("root_cause", "")}

Hypothesis:
{state.get("hypothesis", "")}

Runbook Used: {state.get("runbook_title", "")}

Remediation:
{state.get("remediation_result", "")}

Incident Report Summary:
{state.get("incident_report", "")[:500]}
""".strip()


def _estimate_duration(state: dict) -> str:
    """Estimate incident duration from state."""
    # In production: track start/end timestamps
    severity_durations = {"P0": "45", "P1": "23", "P2": "12", "P3": "5"}
    return severity_durations.get(state.get("severity", "P1"), "unknown")


def format_memory_for_prompt(similar_incidents: list[dict]) -> str:
    """
    Format past incidents into a prompt-friendly string.
    Injected into the root cause reasoning prompt.
    """
    if not similar_incidents:
        return "No similar past incidents found."

    lines = ["SIMILAR PAST INCIDENTS (use these to reason faster):"]

    for i, inc in enumerate(similar_incidents, 1):
        lines.append(f"""
[{i}] {inc['incident_id']} — {inc['similarity']:.0%} similar — {inc['occurred_at'][:10]}
    Services : {', '.join(inc['services'])}
    Severity : {inc['severity']}
    Root Cause: {inc['root_cause'][:200]}
    Resolution: {inc['resolution'][:150]}
    Duration  : {inc['duration_min']} min
""")

    return "\n".join(lines)


SEED_INCIDENTS = [
    {
        "alert": {
            "title": "High error rate on checkout-service — v2.3.0 deploy",
            "metric": "error_rate", "value": "6.1%",
        },
        "severity": "P1",
        "affected_services": ["checkout-service", "payment-gateway"],
        "root_cause": "Missing index on orders(user_id) introduced in deployment v2.3.0 caused full table scans. DB connection pool exhausted under production load.",
        "hypothesis": "DB connection pool exhaustion from missing index after deployment",
        "remediation_result": "rollback_deployment on checkout-service: rolled back to v2.2.9 successfully",
        "runbook_title": "Database Connection Pool Exhaustion",
        "confidence": 0.96,
        "ticket_id": "INC-2831",
        "incident_report": "P1 incident resolved by rolling back checkout-service to v2.2.9. Root cause was missing DB index causing pool exhaustion.",
    },
    {
        "alert": {
            "title": "auth-service Redis connection failure — all regions",
            "metric": "availability", "value": "0%",
        },
        "severity": "P0",
        "affected_services": ["auth-service"],
        "root_cause": "Redis pod OOMKilled due to memory pressure from cache key explosion. Auth service lost session store entirely.",
        "hypothesis": "Redis OOMKilled causing auth failures",
        "remediation_result": "restart_service on redis: restarted successfully. clear_cache: cleared 48291 stale keys",
        "runbook_title": "Redis Connection Failure",
        "confidence": 0.93,
        "ticket_id": "INC-2798",
        "incident_report": "P0 resolved by restarting Redis and clearing stale cache keys. Added memory alert at 80%.",
    },
    {
        "alert": {
            "title": "Search latency spike — ES rebalancing eu-west-1",
            "metric": "p99_latency_ms", "value": "5200",
        },
        "severity": "P2",
        "affected_services": ["search-service"],
        "root_cause": "Elasticsearch shard rebalancing triggered by scheduled node rotation. Self-resolved after 18 minutes.",
        "hypothesis": "ES shard rebalancing causing elevated latency",
        "remediation_result": "No automated action taken — self-resolving. Monitoring continued.",
        "runbook_title": "Elasticsearch Shard Rebalancing",
        "confidence": 0.88,
        "ticket_id": "INC-2756",
        "incident_report": "P2 resolved naturally. ES shard rebalancing completed in 18 min. Added YELLOW cluster alert.",
    },
]


def seed_memory(force: bool = False) -> int:
    """
    Seed ChromaDB with past incidents for demo purposes.
    In production: real incidents accumulate automatically.
    Call once: python -m agent.memory
    """
    collection = _get_collection()

    if not force and collection.count() > 0:
        print(f"[memory] Already seeded ({collection.count()} incidents) — skipping")
        print(f"         Use --force to re-seed")
        return collection.count()

    print("[memory] Seeding past incidents...")

    for inc in SEED_INCIDENTS:
        store_incident(inc)

    print(f"[memory]  Seeded {len(SEED_INCIDENTS)} past incidents")
    return collection.count()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force",  action="store_true", help="Force re-seed")
    parser.add_argument("--query",  type=str, help="Test a recall query")
    parser.add_argument("--list",   action="store_true", help="List all stored incidents")
    args = parser.parse_args()

    if args.list:
        col = _get_collection()
        print(f"Total incidents in memory: {col.count()}")
        if col.count() > 0:
            results = col.get(include=["metadatas"])
            for meta in results["metadatas"]:
                print(f"  {meta['incident_id']} | {meta['severity']} | {meta['title'][:50]}")

    else:
        seed_memory(force=args.force)

    if args.query:
        print(f"\nTest recall: '{args.query}'")
        results = recall_similar_incidents(args.query)
        if results:
            print(format_memory_for_prompt(results))