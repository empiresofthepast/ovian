"""MQTT side of the server.

The server is a superuser client of the broker. It publishes private player
events, public map changes and chat, and subscribes to topics where clients
may publish (for example the chat inbox).

Topic layout (``{root}`` is ``ovian/{world_id}``):

- ``{root}/player/{player_id}/events``  private events for one player
- ``{root}/map``                        public map changes
- ``{root}/chat/{channel}``             chat messages, stamped by the server
- ``{root}/chat/{channel}/in/{player}`` where a client posts chat (ACL-checked)
- ``{root}/server``                     server announcements
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .game import Game
    from .modules.base import MqttHandler

MAX_PACKET = 1_048_000  # mosquitto max_packet_size is 1 MiB (broker/mosquitto.conf.template), headers included
log = logging.getLogger("ovian.realtime")


class Topics:
    def __init__(self, world_id: str):
        self.root = f"ovian/{world_id}"

    def player(self, player_id: int) -> str:
        return f"{self.root}/player/{player_id}/events"

    @property
    def map(self) -> str:
        return f"{self.root}/map"

    def chat(self, channel: str) -> str:
        return f"{self.root}/chat/{channel}"

    def chat_in(self, channel: str, player_id: int) -> str:
        return f"{self.root}/chat/{channel}/in/{player_id}"

    @property
    def server(self) -> str:
        return f"{self.root}/server"


def topic_matches(filter_: str, topic: str) -> bool:
    """MQTT filter matching (+ and #)."""
    f, t = filter_.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


def filter_covers(allowed: str, requested: str) -> bool:
    """True when every topic matched by ``requested`` is also matched by ``allowed``."""
    a, r = allowed.split("/"), requested.split("/")
    for i, part in enumerate(a):
        if part == "#":
            return True
        if i >= len(r):
            return False
        if r[i] == "#":
            return False
        if part != "+" and (r[i] == "+" or part != r[i]):
            return False
    return len(a) == len(r)


class Realtime:
    """Publishes through a bounded in-memory queue so game code never blocks on the broker."""

    def __init__(self, game: Game, url: str, username: str, password: str, max_queue: int = 10_000):
        self.game = game
        self.url = urlparse(url) if url else None
        self.username = username
        self.password = password
        self.queue: deque[tuple[str, bytes]] = deque(maxlen=max_queue)
        self.wakeup = asyncio.Event()
        self.handlers: dict[str, MqttHandler] = {}
        self.connected = False

    def subscribe(self, filter_: str, handler: MqttHandler) -> None:
        self.handlers[f"{self.game.topics.root}/{filter_}"] = handler

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.queue.append((topic, json.dumps(payload, separators=(",", ":")).encode()))
        self.wakeup.set()

    async def run(self) -> None:
        if not self.url:
            log.warning("OVIAN_MQTT_URL is empty: realtime disabled, events are dropped")
            return
        import aiomqtt

        delay = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.url.hostname or "localhost",
                    port=self.url.port or 1883,
                    username=self.username,
                    password=self.password,
                    identifier=f"ovian-server-{self.game.settings.world_id}-{id(self)}",
                ) as client:
                    self.connected = True
                    delay = 1.0
                    log.info("connected to MQTT broker %s", self.url.netloc)
                    for f in self.handlers:
                        await client.subscribe(f, qos=1)
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._pump(client))
                        tg.create_task(self._read(client))
            except asyncio.CancelledError:
                raise
            except BaseException as e:  # noqa: BLE001 - reconnect on anything
                self.connected = False
                log.warning("MQTT connection lost (%s), retrying in %.0fs", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _pump(self, client: Any) -> None:
        while True:
            while self.queue:
                topic, payload = self.queue[0]
                if len(payload) + len(topic) > MAX_PACKET:
                    # the broker drops the connection on an oversize packet; retrying it would wedge the queue
                    log.error("dropping %d-byte message on %s: over the broker's packet limit", len(payload), topic)
                    self.queue.popleft()
                    continue
                await client.publish(topic, payload, qos=1)
                self.queue.popleft()
            self.wakeup.clear()
            await self.wakeup.wait()

    async def _read(self, client: Any) -> None:
        async for message in client.messages:
            topic = str(message.topic)
            for f, handler in self.handlers.items():
                if topic_matches(f, topic):
                    try:
                        await handler(self.game, topic, bytes(message.payload))
                    except Exception:
                        log.exception("MQTT handler for %s failed", topic)

    async def deliver(self, topic: str, payload: bytes) -> None:
        """Feed an incoming message to handlers directly (used by tests)."""
        for f, handler in self.handlers.items():
            if topic_matches(f, topic):
                await handler(self.game, topic, payload)


class RecordingRealtime(Realtime):
    """Keeps every published message in ``sent``. Used when MQTT is disabled in tests."""

    def __init__(self, game: Game):
        super().__init__(game, "", "", "")
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.sent.append((topic, payload))

    def to(self, topic: str) -> list[dict[str, Any]]:
        return [p for t, p in self.sent if t == topic]
