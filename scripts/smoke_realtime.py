"""End-to-end smoke test of the running stack: REST + MQTT over WebSocket.

    docker compose up -d --build
    docker run --rm --network ovian_default -v "$PWD/scripts:/s:ro" python:3.12-slim \
      sh -c "pip -q install paho-mqtt httpx && python /s/smoke_realtime.py"

Env: OVIAN_API (default http://server:8000), OVIAN_WS_HOST/OVIAN_WS_PORT (broker:9001).
"""

from __future__ import annotations

import json
import os
import queue
import sys
import time
import uuid

import httpx
import paho.mqtt.client as mqtt

API = os.environ.get("OVIAN_API", "http://server:8000") + "/api/v1"
WS_HOST = os.environ.get("OVIAN_WS_HOST", "broker")
WS_PORT = int(os.environ.get("OVIAN_WS_PORT", "9001"))
failures = 0


def check(cond: bool, what: str) -> None:
    global failures
    print(("PASS " if cond else "FAIL ") + what)
    failures += 0 if cond else 1


def register(name: str) -> dict:
    tribe = httpx.get(f"{API}/content").json()["tribes"][0]["id"]  # works with any pack
    r = httpx.post(f"{API}/auth/register", json={"username": name, "password": "password123", "tribe": tribe})
    r.raise_for_status()
    return r.json()


class Client:
    def __init__(self, username: str, password: str):
        self.inbox: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.granted: dict[int, list] = {}
        self.connected = queue.Queue()
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"smoke-{uuid.uuid4().hex[:8]}", transport="websockets")
        self.c.username_pw_set(username, password)
        self.c.on_connect = lambda c, u, f, rc, p: self.connected.put(rc)
        self.c.on_message = lambda c, u, m: self.inbox.put((m.topic, json.loads(m.payload)))
        self.c.on_subscribe = lambda c, u, mid, rcs, p: self.granted.__setitem__(mid, rcs)
        self.c.connect(WS_HOST, WS_PORT)
        self.c.loop_start()

    def rc(self):
        return self.connected.get(timeout=5)

    def subscribe(self, topic: str) -> bool:
        _, mid = self.c.subscribe(topic, qos=1)
        for _ in range(50):
            if mid in self.granted:
                return not self.granted[mid][0].is_failure
            time.sleep(0.1)
        return False

    def wait(self, pred, timeout: float = 5.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                topic, msg = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if pred(topic, msg):
                return msg
        return None


def main() -> int:
    world = httpx.get(f"{API}/world").json()
    root = world["topic_root"]
    suffix = uuid.uuid4().hex[:6]
    alice, bob = register(f"alice{suffix}"), register(f"bob{suffix}")
    aid, bid = alice["player"]["id"], bob["player"]["id"]

    bad = Client(str(aid), "not-a-token")
    check(bad.rc().is_failure, "a bad token is refused by the broker")
    bad.c.loop_stop()

    a = Client(str(aid), alice["token"])
    check(not a.rc().is_failure, "a player connects with the API token")
    check(a.subscribe(f"{root}/player/{aid}/events"), "may subscribe to own events")
    check(a.subscribe(f"{root}/chat/+"), "may subscribe to chat channels")
    check(a.subscribe(f"{root}/map"), "may subscribe to the map")
    check(not a.subscribe(f"{root}/player/{bid}/events"), "may not subscribe to someone else's events")
    check(not a.subscribe("#"), "may not subscribe to everything")

    headers = {"Authorization": f"Bearer {alice['token']}"}
    r = httpx.post(f"{API}/villages/{alice['village_id']}/build", json={"slot": 0}, headers=headers)
    check(r.status_code == 200, "REST build order accepted")
    msg = a.wait(lambda t, m: t.endswith(f"/player/{aid}/events") and m["type"] == "village.updated")
    check(msg is not None and len(msg["data"]["build_queue"]) == 1, "village.updated pushed over MQTT")

    a.c.publish(f"{root}/chat/global/in/{aid}", json.dumps({"text": f"hi from {suffix}"}), qos=1)
    msg = a.wait(lambda t, m: t == f"{root}/chat/global" and m["data"]["text"] == f"hi from {suffix}")
    check(msg is not None and msg["data"]["from"]["id"] == aid, "chat is stamped with the real sender")

    a.c.publish(f"{root}/chat/global/in/{bid}", json.dumps({"text": f"spoof {suffix}"}), qos=1)
    msg = a.wait(lambda t, m: t == f"{root}/chat/global" and "spoof" in m["data"]["text"], timeout=3)
    check(msg is None, "cannot post chat as another player")

    a.c.loop_stop()
    print(f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
