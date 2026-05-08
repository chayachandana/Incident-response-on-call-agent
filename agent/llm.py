"""
LLM Configuration — Ollama (local, no API key)
===============================================
Uses langchain-ollama to run Mistral locally.
Falls back to MockLLM for demo/testing.

Setup:
  brew install ollama
  ollama pull mistral
  ollama serve

Or skip Ollama entirely for now:
  set USE_MOCK_LLM=1 in your .env
"""

import os
from langchain_core.messages import AIMessage


def get_llm(model: str = "mistral"):
    """
    Returns Ollama LLM instance.
    Set OLLAMA_MODEL in .env to override (e.g. 'llama3.1', 'deepseek-coder').
    Set USE_MOCK_LLM=1 to run without Ollama installed.
    """
    model = os.getenv("OLLAMA_MODEL", model)

    if os.getenv("USE_MOCK_LLM"):
        return MockLLM()

    try:
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model,
            temperature=0.1,
            num_predict=1024,
            num_ctx=4096,
        )
    except ImportError:
        raise ImportError(
            "Run: pip install langchain-ollama\n"
            "Then: ollama pull mistral\n"
            "Or set USE_MOCK_LLM=1 in .env to skip Ollama"
        )


class MockLLM:
    """
    Mock LLM for testing without Ollama running.
    Returns realistic SRE-style outputs for each prompt type.
    """

    def invoke(self, prompt: str) -> AIMessage:

        # ingest_alert — returns severity JSON
        if '"severity"' in prompt and "P0|P1" in prompt:
            return AIMessage(content="""{
  "severity": "P1",
  "affected_services": ["checkout-service", "payment-gateway"],
  "alert_type": "error_rate",
  "summary": "Elevated error rate on checkout-service causing payment failures"
}""")

        # analyze_root_cause — returns reasoning JSON
        if "confidence" in prompt and "hypothesis" in prompt:
            return AIMessage(content="""{
  "hypothesis": "DB connection pool exhaustion on checkout-service caused by missing index on orders table after deployment v2.4.1",
  "root_cause": "Missing index on orders(user_id) introduced in deployment v2.4.1 causing full table scans. Under production load, DB connections held longer, exhausting pool (max 50). Cascading 503s to payment-gateway.",
  "confidence": 0.94,
  "recommended_action": "Rollback checkout-service to v2.4.0 immediately",
  "needs_more_evidence": false,
  "missing_evidence": ""
}""")

        # generate_report — returns postmortem
        if "postmortem" in prompt.lower() or "incident report" in prompt.lower():
            return AIMessage(content="""## Incident Report

### 1. Executive Summary
A P1 incident affecting checkout-service and payment-gateway resulted in an 8.3% error rate for 23 minutes. Root cause was database connection pool exhaustion triggered by a missing index deployed at 14:15 UTC.

### 2. Timeline
- 14:15 UTC — Deployment v2.4.1 to checkout-service (missing index on orders.user_id)
- 14:23 UTC — Error rate crosses 1% threshold, alert fires
- 14:23 UTC — Incident Response Agent activated
- 14:24 UTC — Root cause identified (confidence: 94%)
- 14:25 UTC — Payments team paged, Slack thread opened
- 14:46 UTC — Rollback to v2.4.0 complete, error rate returns to baseline

### 3. Root Cause
Missing database index on orders(user_id) introduced in deployment v2.4.1 caused full table scans on every checkout request. Under production load, DB connections were held longer, exhausting the pool (max: 50 connections).

### 4. Impact Assessment
- Duration: 23 minutes
- Error rate peak: 8.3%
- Estimated affected checkouts: ~4,200 requests

### 5. Actions Taken
- Payments on-call team paged via PagerDuty
- Rollback of checkout-service to v2.4.0 initiated
- Slack thread opened in #incidents

### 6. Prevention
- Add DB migration review checklist to deployment runbook
- Add automated index coverage check to CI pipeline
- Set connection pool alert at 70% threshold""")

        # fallback
        return AIMessage(content="Analysis complete. Proceed with investigation.")