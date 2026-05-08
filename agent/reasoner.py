import json
import re
from agent.llm import get_llm
from agent.memory import format_memory_for_prompt


CONFIDENCE_THRESHOLD = 0.92
MAX_RETRIES = 3


def build_evidence_summary(logs: list, metrics: list) -> str:
    log_block = "\n".join([
        f"  [{l['timestamp']}] {l['service']} {l['level']}: {l['message']}"
        for l in logs[-20:]
    ]) or "  (no logs fetched yet)"

    metric_block = "\n".join([
        f"  {m['service']}.{m['metric']}: {m['latest_value']} {m['unit']}"
        f"{'  ⚠️  ANOMALOUS' if m['anomaly'] else ''}"
        for m in metrics
    ]) or "  (no metrics fetched yet)"

    return f"LOGS:\n{log_block}\n\nMETRICS:\n{metric_block}"


def reason(
    alert: dict,
    logs: list,
    metrics: list,
    previous_hypothesis: str = "",
    retry_count: int = 0,
    similar_incidents: list = None,        # ← NEW
) -> dict:
    """
    Run one reasoning iteration.
    Now includes similar past incidents in the prompt.
    """
    llm = get_llm()
    evidence = build_evidence_summary(logs, metrics)

    # Format past incidents for prompt injection
    memory_block = format_memory_for_prompt(similar_incidents or [])

    retry_context = ""
    if retry_count > 0 and previous_hypothesis:
        retry_context = f"""
Previous hypothesis (attempt {retry_count}):
{previous_hypothesis}

You have MORE evidence now. Update your analysis accordingly.
"""

    prompt = f"""You are an expert SRE performing autonomous root cause analysis.
This is reasoning attempt {retry_count + 1} of {MAX_RETRIES}.

ALERT:
  title:     {alert.get('title')}
  service:   {alert.get('service')}
  metric:    {alert.get('metric')}: {alert.get('value')} (threshold: {alert.get('threshold')})
  env:       {alert.get('environment')}
  triggered: {alert.get('triggered_at')}
{retry_context}
{memory_block}

CURRENT EVIDENCE:
{evidence}

Use the past incidents above to reason faster — if this looks similar, apply
the same root cause logic. If it's different, explain why.

Respond ONLY with this exact JSON (no markdown, no extra text):
{{
  "hypothesis": "one sentence: what is happening and why",
  "root_cause": "specific technical root cause with evidence reference",
  "confidence": 0.0,
  "recommended_action": "most important immediate action",
  "needs_more_evidence": true,
  "missing_evidence": "what would increase your confidence"
}}

Confidence guide:
  0.95+ : certain, direct evidence, clear root cause
  0.85  : strong indicators, one ambiguous piece
  0.70  : plausible but needs corroboration
  0.50  : multiple possible causes
  <0.50 : insufficient evidence

Be honest. Do not inflate confidence.
"""

    response = llm.invoke(prompt)
    content = response.content.strip()

    if "```" in content:
        content = re.sub(r"```json?\n?", "", content)
        content = content.replace("```", "").strip()

    try:
        parsed = json.loads(content)
        parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
        return parsed
    except (json.JSONDecodeError, KeyError, ValueError):
        return {
            "hypothesis":          content[:200],
            "root_cause":          "Unable to parse structured response",
            "confidence":          0.4,
            "recommended_action":  "Manually investigate",
            "needs_more_evidence": True,
            "missing_evidence":    "All available data",
        }