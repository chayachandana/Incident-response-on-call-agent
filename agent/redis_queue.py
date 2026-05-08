# agent/redis_queue.py
import redis
import json
import os
import time
import threading
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
ALERT_CHANNEL = "alerts"


def get_redis_client():
    return redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_keepalive=True,
        socket_keepalive_options={},
        retry_on_timeout=True,
        health_check_interval=30,
    )


def publish_alert(alert: dict):
    client = get_redis_client()
    payload = json.dumps(alert)
    client.publish(ALERT_CHANNEL, payload)
    print(f"[queue] Published alert: {alert['title']}")


def subscribe_and_run(on_alert_callback):
    print(f"[queue] Subscribed to '{ALERT_CHANNEL}' channel. Waiting for alerts...")

    def _listen():
        while True:  # reconnect loop
            try:
                client = get_redis_client()
                pubsub = client.pubsub()
                pubsub.subscribe(ALERT_CHANNEL)

                for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            alert = json.loads(message["data"])
                            print(f"\n[queue] 🚨 Alert received: {alert.get('title')}")
                            on_alert_callback(alert)
                        except Exception as e:
                            print(f"[queue] ❌ Error processing alert: {e}")

            except redis.exceptions.ConnectionError as e:
                print(f"[queue] ⚠️  Redis disconnected: {e}")
                print(f"[queue] 🔄 Reconnecting in 3 seconds...")
                time.sleep(3)
            except Exception as e:
                print(f"[queue] ❌ Unexpected error: {e}")
                time.sleep(3)

    thread = threading.Thread(target=_listen, daemon=True)
    thread.start()
    return thread