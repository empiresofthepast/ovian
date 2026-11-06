from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest
import pytest_asyncio

from ovian_server.app import create_app
from ovian_server.clock import ManualClock
from ovian_server.config import Settings
from ovian_server.game import Game
from ovian_server.modules import chat
from ovian_server.realtime import RecordingRealtime

ROOT = Path(__file__).resolve().parents[2]
TABLES = "players, villages, jobs, movements, stationed, reports, chat_messages, alliances, world_state, hall_of_fame"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(marker, append=False)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("OVIAN_TEST_DATABASE_URL", "postgresql://ovian:ovian@localhost:5432/ovian_test"),
        content_dir=str(ROOT / "content" / "classic"),
        scheduler_enabled=False,
        mqtt_url="",
        jwt_secret="test-secret-that-is-long-enough-for-hs256",
        internal_key="test-key",
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def game(settings: Settings) -> AsyncIterator[Game]:
    g = Game(settings, clock=ManualClock())
    g.realtime = RecordingRealtime(g)
    g.content.extensions["terrain"] = {"per_tile": {}}  # no terrain bonus: spawns are random (test_frontier turns it on)
    for m in g.modules:
        for f, h in m.mqtt.items():
            g.realtime.subscribe(f, h)
    app = create_app(settings, g)
    async with app.router.lifespan_context(app):
        await g.pool.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        g.app = app  # type: ignore[attr-defined]
        yield g


@pytest_asyncio.fixture(loop_scope="session")
async def client(game: Game) -> AsyncIterator[httpx.AsyncClient]:
    await game.pool.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
    game.realtime.sent.clear()
    chat._last_post.clear()
    for cache in ("_governments", "_banned"):
        game.__dict__.pop(cache, None)
    transport = httpx.ASGITransport(app=game.app)  # type: ignore[attr-defined]
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


class Player:
    def __init__(self, client: httpx.AsyncClient, data: dict[str, Any]):
        self.client = client
        self.token = data["token"]
        self.id = data["player"]["id"]
        self.village_id = data["village_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.client.get(path, headers=self.headers, **kw)

    async def post(self, path: str, json: Any = None) -> httpx.Response:
        return await self.client.post(path, headers=self.headers, json=json)

    async def delete(self, path: str) -> httpx.Response:
        return await self.client.delete(path, headers=self.headers)

    async def village(self, vid: int | None = None) -> dict[str, Any]:
        r = await self.get(f"/villages/{vid or self.village_id}")
        assert r.status_code == 200, r.text
        return r.json()


@pytest_asyncio.fixture(loop_scope="session")
async def register(client: httpx.AsyncClient):
    async def make(name: str, tribe: str = "clans") -> Player:
        r = await client.post("/auth/register", json={"username": name, "password": "password123", "tribe": tribe})
        assert r.status_code == 201, r.text
        return Player(client, r.json())

    return make


async def patch_state(game: Game, village_id: int, fn) -> None:
    """Edit a village's engine state directly (test setup shortcut)."""
    state = await game.pool.fetchval("SELECT state FROM villages WHERE id = $1", village_id)
    fn(state)
    await game.pool.execute("UPDATE villages SET state = $2 WHERE id = $1", village_id, state)


def give_buildings(state: dict[str, Any], **levels: int) -> None:
    """Place center buildings by id, reusing their slot if present."""
    for building, level in levels.items():
        slot = next((s for s in state["slots"] if s["building"] == building), None) or next(
            s for s in state["slots"][18:] if s["building"] is None
        )
        slot["building"], slot["level"] = building, level


def rich(state: dict[str, Any]) -> None:
    state["resources"] = {r: 100_000 for r in state["resources"]}
