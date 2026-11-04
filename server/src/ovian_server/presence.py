"""When players were last seen: any authenticated API call, MQTT connection or client heartbeat.

Touches are kept in memory and written in batches, at most one per player every
``THROTTLE_MS``, so presence costs no database write per request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game

log = logging.getLogger("ovian.presence")
THROTTLE_MS = 30_000
# Seen within this window counts as online.
ONLINE_MS = 3 * 60_000


class Presence:
    def __init__(self, game: Game):
        self.game = game
        self.pending: dict[int, int] = {}
        self.written: dict[int, int] = {}

    def touch(self, player_id: int) -> None:
        now = self.game.clock.now()
        if now - self.written.get(player_id, 0) >= THROTTLE_MS:
            self.pending[player_id] = now

    async def flush(self) -> None:
        if not self.pending or self.game.pool is None:
            return
        batch, self.pending = self.pending, {}
        await self.game.pool.execute(
            """UPDATE players p SET last_seen_at = greatest(coalesce(p.last_seen_at, 0), s.at)
               FROM unnest($1::bigint[], $2::bigint[]) AS s(id, at) WHERE p.id = s.id""",
            list(batch), list(batch.values()),
        )
        self.written.update(batch)

    async def run(self, interval: float = 10.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except Exception:
                log.exception("presence flush failed")
