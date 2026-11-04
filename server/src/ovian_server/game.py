"""The Game object: everything a module needs, created once per process."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, AsyncIterator

import asyncpg
import pluggy

from .clock import Clock
from .config import Settings
from .content import Content, load_content
from .hooks import plugin_manager
from .modules.base import JobHandler, Module
from .realtime import Realtime, Topics

log = logging.getLogger("ovian.game")


@dataclass
class Tx:
    """A database transaction plus the realtime messages to send once it commits."""

    conn: asyncpg.Connection
    outbox: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.outbox.append((topic, payload))


class Game:
    def __init__(self, settings: Settings, clock: Clock | None = None, realtime: Realtime | None = None):
        self.settings = settings
        self.clock = clock or Clock()
        self.topics = Topics(settings.world_id)
        self.pm: pluggy.PluginManager = plugin_manager()
        self._load_plugins()
        self.content: Content = load_content(settings.content_dir, self.pm, settings.world_speed)
        self.modules: list[Module] = [m for mods in self.pm.hook.ovian_modules() for m in mods]
        self.jobs: dict[str, JobHandler] = {}
        for m in self.modules:
            for kind, handler in m.jobs.items():
                if kind in self.jobs:
                    raise RuntimeError(f"job kind {kind!r} registered twice (module {m.name})")
                self.jobs[kind] = handler
        self.realtime = realtime or Realtime(
            self, settings.mqtt_url, settings.mqtt_service_user, settings.mqtt_service_password
        )
        self.realtime.game = self
        for m in self.modules:
            for f, handler in m.mqtt.items():
                self.realtime.subscribe(f, handler)
        from .presence import Presence

        self.presence = Presence(self)
        self.pool: asyncpg.Pool | None = None
        self.wakeup = asyncio.Event()

    @property
    def engine(self):  # noqa: ANN201 - ovian_engine.Engine
        return self.content.engine

    @property
    def hook(self) -> Any:
        return self.pm.hook

    async def emit(self, hook: str, **kwargs: Any) -> list[Any]:
        """Call a hook; implementations may be plain or ``async def``. Returns the results."""
        results = getattr(self.pm.hook, hook)(**kwargs)
        out: list[Any] = []
        try:
            for r in results:
                out.append(await r if inspect.isawaitable(r) else r)
        finally:
            for r in results:  # a veto skips the rest; don't leak unawaited coroutines
                if inspect.iscoroutine(r) and r.cr_frame is not None and not r.cr_running:
                    r.close()
        return out

    def _load_plugins(self) -> None:
        from . import modules as builtin

        from .modules import (alliances, calendar, chronicle, contentment, culture, gods, governments, great, heroes, market, medals, omens,
                              player_rules, pve, roads, rounds, starvation, submission, ver_sacrum, embassies, archaeology, auxiliaries, governors)

        self.pm.register(builtin, name="ovian.builtin")
        self.pm.register(culture, name="ovian.culture")
        self.pm.register(submission, name="ovian.submission")
        self.pm.register(ver_sacrum, name="ovian.ver_sacrum")
        for mod in (alliances, market, heroes, pve, gods, great, player_rules, chronicle, contentment, governments, calendar, omens, medals,
                    rounds, roads, starvation, embassies, archaeology, auxiliaries, governors):
            self.pm.register(mod, name=f"ovian.{mod.__name__.rsplit('.', 1)[-1]}")
        disabled = set(Settings.split(self.settings.disabled_plugins))
        for ep in entry_points(group="ovian.plugins"):
            if ep.name in disabled:
                continue
            try:
                self.pm.register(ep.load(), name=f"ep:{ep.name}")
                log.info("loaded plugin %s", ep.name)
            except Exception:
                log.exception("failed to load plugin %s", ep.name)
                raise
        for path in Settings.split(self.settings.plugins):
            self.pm.register(importlib.import_module(path), name=path)
            log.info("loaded plugin %s", path)

    @asynccontextmanager
    async def tx(self) -> AsyncIterator[Tx]:
        assert self.pool is not None, "database not connected"
        async with self.pool.acquire() as conn:
            t = Tx(conn)
            async with conn.transaction():
                yield t
        for topic, payload in t.outbox:
            self.realtime.publish(topic, payload)

    async def schedule(self, tx: Tx, kind: str, due_at: int, payload: dict[str, Any], village_id: int | None = None) -> int:
        if kind not in self.jobs:
            raise ValueError(f"no handler for job kind {kind!r}")
        job_id = await tx.conn.fetchval(
            "INSERT INTO jobs(kind, due_at, village_id, payload) VALUES ($1, $2, $3, $4) RETURNING id",
            kind, due_at, village_id, payload,
        )
        self.wakeup.set()
        return job_id

    def event(self, tx: Tx, player_id: int, type_: str, data: dict[str, Any]) -> None:
        """Queue a private event for a player, sent after commit."""
        tx.publish(self.topics.player(player_id), {"type": type_, "at": self.clock.now(), "data": data})

    # ---------------------------------------------------------------- scheduler

    async def run_due(self, limit: int = 1000) -> int:
        """Process due jobs one transaction each, oldest first. Returns how many ran."""
        done = 0
        while done < limit:
            now = self.clock.now()
            job: dict[str, Any] | None = None
            try:
                async with self.tx() as tx:
                    row = await tx.conn.fetchrow(
                        "SELECT * FROM jobs WHERE NOT failed AND due_at <= $1 ORDER BY due_at, id LIMIT 1 FOR UPDATE SKIP LOCKED",
                        now,
                    )
                    if row is None:
                        return done
                    job = dict(row)
                    handler = self.jobs.get(job["kind"])
                    if handler is None:
                        raise LookupError(f"no handler for job kind {job['kind']!r}")
                    # Delete first so views pushed by the handler no longer list this job.
                    # The transaction rolls the delete back if the handler fails.
                    await tx.conn.execute("DELETE FROM jobs WHERE id = $1", job["id"])
                    await handler(self, tx, job)
            except Exception as e:  # noqa: BLE001
                log.exception("job %s failed", job and job["id"])
                if job is None:
                    raise
                await self._job_failed(job, e)
            done += 1
        return done

    async def _job_failed(self, job: dict[str, Any], error: Exception) -> None:
        attempts = job["attempts"] + 1
        assert self.pool is not None
        await self.pool.execute(
            "UPDATE jobs SET attempts = $2, failed = $3, last_error = $4, due_at = $5 WHERE id = $1",
            job["id"], attempts, attempts >= 5, repr(error)[:2000], self.clock.now() + 1000 * 2**attempts,
        )

    async def run_scheduler(self) -> None:
        interval = self.settings.scheduler_interval
        while True:
            try:
                ran = await self.run_due()
            except Exception:
                log.exception("scheduler loop error")
                ran = 0
            if ran == 0:
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), timeout=interval)
                except TimeoutError:
                    pass
