"""Abandoned cities fall to the barbarians.

``extensions.abandon``::

    abandon:
      days: 7            # real days without being seen before a player's cities are given up
      every_minutes: 60  # how often the world looks for them
      per_level: 400     # population per camp level (capped by camps.max_level)

A player who has not been seen for ``days`` (not on vacation, not a bot) loses every city:
each becomes a barbarian camp, "Ruins of <name>", with the troops and stores it had (or a
camp garrison when it had none). Its vassals go free, its own overlord lets it go, foreign
troops stationed there march home and its trade routes and offers end. Like any camp it can
be raided, and settlers can found a colony there. A player who comes back with no city left
starts afresh with a new one.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from ..hooks import hookimpl
from ..repo import get_village, save_village
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

SWEEP = "abandon.sweep"


def cfg(game: Game) -> dict[str, float] | None:
    c = game.content.extensions.get("abandon")
    if c is None:
        return None
    return {"days": float(c.get("days", 7)), "every_minutes": float(c.get("every_minutes", 60)), "per_level": float(c.get("per_level", 400))}


async def abandon_player(game: Game, tx: Tx, player_id: int) -> int:
    """Give every city of a player to the barbarians. Returns how many fell."""
    from . import pve
    from .chronicle import record
    from .military import dispatch
    from .submission import release
    from .villages import BUILD, RESEARCH, TRAIN

    c = cfg(game) or {"per_level": 400.0}
    conn = tx.conn
    npc = await pve.npc_id(game, conn)
    name = await conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
    ids = [r["id"] for r in await conn.fetch("SELECT id FROM villages WHERE player_id = $1 ORDER BY id", player_id)]
    max_level = int(pve.cfg(game)["max_level"])
    now = game.clock.now()
    for vid in ids:
        v = await get_village(conn, vid, lock=True)
        for row in await conn.fetch("SELECT vassal_id FROM vassals WHERE overlord_id = $1", v.id):
            await release(game, tx, await get_village(conn, row["vassal_id"], lock=True), "abandoned")
        await release(game, tx, v, "abandoned")
        v = await get_village(conn, vid, lock=True)
        for s in await conn.fetch("SELECT * FROM stationed WHERE host_id = $1", v.id):
            await conn.execute("DELETE FROM stationed WHERE id = $1", s["id"])
            home = await get_village(conn, s["home_id"])
            await dispatch(game, tx, "return", home.player_id, home, v, home, s["units"])
        await conn.execute("DELETE FROM jobs WHERE village_id = $1 AND kind = ANY($2::text[])", v.id, [BUILD, TRAIN, RESEARCH])
        await conn.execute("DELETE FROM trade_routes WHERE village_id = $1", v.id)
        await conn.execute("DELETE FROM trade_offers WHERE village_id = $1", v.id)
        level = max(1, min(max_level, math.ceil((v.population or 0) / c["per_level"])))
        units = {u: n for u, n in (v.state.get("units") or {}).items() if n > 0}
        if not units:
            v.state["units"] = pve.garrison(game, level, random.Random())
        old = v.name
        v.name = f"Ruins of {old}"[:40]
        v.meta = {"camp": {"level": level}, "abandoned": {"player": name, "at": now, "name": old}}
        v.player_id = npc
        await conn.execute("UPDATE villages SET player_id = $2, name = $3 WHERE id = $1", v.id, npc, v.name)
        await save_village(game, tx, v)
        tx.publish(game.topics.map, {"type": "map.village_changed", "at": now, "data": v.public()})
        await record(game, tx, "abandoned", f"{old} was abandoned by {name}; the barbarians moved in", village=v, data={"player": name})
    return len(ids)


async def sweep(game: Game, tx: Tx) -> int:
    c = cfg(game)
    if c is None:
        return 0
    now = game.clock.now()
    cutoff = now - int(c["days"] * 86_400_000)
    rows = await tx.conn.fetch(
        """SELECT p.id FROM players p WHERE NOT p.npc AND NOT p.bot AND p.vacation_until <= $1
             AND coalesce(p.last_seen_at, p.last_login_at, p.created_at) < $2
             AND EXISTS (SELECT 1 FROM villages v WHERE v.player_id = p.id)""",
        now, cutoff)
    n = 0
    for r in rows:
        n += await abandon_player(game, tx, r["id"])
    return n


async def on_sweep(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await sweep(game, tx)
    c = cfg(game)
    if c is not None:
        await game.schedule(tx, SWEEP, game.clock.now() + int(c["every_minutes"] * 60_000), {})


async def fresh_start(game: Game, player_id: int) -> None:
    """A player back with no city left gets a new one."""
    from .auth import found_village

    async with game.tx() as tx:
        p = await tx.conn.fetchrow("SELECT username, npc FROM players WHERE id = $1 FOR UPDATE", player_id)
        if p is None or p["npc"] or await tx.conn.fetchval("SELECT 1 FROM villages WHERE player_id = $1", player_id):
            return
        await found_village(game, tx, player_id, f"{p['username']}'s village")


@hookimpl
async def ovian_started(game: Game) -> None:
    if cfg(game) is None:
        return
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", SWEEP):
            await game.schedule(tx, SWEEP, game.clock.now() + 60_000, {})


module = Module("abandon", jobs={SWEEP: on_sweep})
