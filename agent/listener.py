"""
Main entrypoint for the event-driven agent.

Run:
  python -m agent.listener

Then in another terminal:
  python scripts/publish_alert.py --sev P1

Watch the agent auto-trigger and process the alert end-to-end.
"""

import time
from dotenv import load_dotenv
load_dotenv()

from agent.redis_queue import subscribe_and_run
from agent.graph import run_incident   


def handle_alert(alert: dict):
    """Called automatically when an alert arrives on the Redis channel."""
    print(f"\n{'='*60}")
    print(f"  AGENT TRIGGERED: {alert['title']}")
    print(f"{'='*60}")

    try:
        result = run_incident(alert)

        print(f"\n Incident handled.")
        print(f"   Severity  : {result['severity']}")
        print(f"   Team paged: {result['team_paged']}")
        print(f"   Ticket    : {result['ticket_id']}")
        print(f"   Status    : {result['status']}")
        print(f"\n Report preview:")
        print(result["incident_report"][:400] + "...")

    except Exception as e:
        print(f" Agent error: {e}")
        raise


if __name__ == "__main__":
    print("🤖 Incident Response Agent — listening for alerts")
    print("   Redis channel: alerts")
    print("   Model: Ollama (mistral)")
    print("\n   Test with: python scripts/publish_alert.py --sev P1\n")

    subscribe_and_run(handle_alert)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nAgent stopped.")