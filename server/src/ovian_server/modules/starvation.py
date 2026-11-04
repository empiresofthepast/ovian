"""Starvation: troops die when the upkeep resource runs out.

A city whose stock of the upkeep resource (food, grain) is empty while it still eats more
than it produces loses troops, a few at a time. Every ``tick_hours`` (game hours, divided by
the world speed) it loses the lowest-ranking troops first (the cheapest, by the sum of their
cost), its own at home and foreign troops stationed there alike, until their upkeep covers
``share`` of the deficit, at least one soldier. It stops as soon as the city feeds itself again.
Buildings eat too, but they never starve; a city short of food with no troops left just stays at zero.

Each owner of starved troops gets a ``starvation`` report. The village view carries
``starvation``: the hourly deficit and when the stock runs out (or ``starving``).

    extensions:
      starvation: { tick_hours: 1, share: 0.25 }
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg

from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_village, hosted_upkeep, save_village
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

TICK = "starvation.tick"


def cfg(game: Game) -> dict[str, Any] | None:
    c = game.content.extensions.get("starvation")
    return None if c is None else {"tick_hours": 1.0, "share": 0.25} | c


def food(game: Game) -> str | None:
    from .contentment import upkeep_resource

    return upkeep_resource(game)


def rank(game: Game, unit: str) -> tuple[float, str]:
    """Lowest-ranking first: the cheapest troops."""
    u = game.content.unit(unit) or {}
    return float(sum((u.get("cost") or {}).values())), unit


def upkeep_of(game: Game, unit: str) -> float:
    return float((game.content.unit(unit) or {}).get("upkeep", 0)) * game.content.pack["world"]["speed"]


async def starve(game: Game, tx: Tx, v: VillageRow) -> dict[int, dict[str, int]]:
    """Kill troops in a (locked, accrued) starving village. Returns the dead by home village id."""
    c, r = cfg(game), food(game)
    if c is None or r is None:
        return {}
    extra = await hosted_upkeep(game, tx.conn, v.id)
    eco = game.engine.economy(v.state, extra)
    deficit = -float(eco["production"].get(r, 0))
    if deficit <= 0 or float(v.state["resources"].get(r, 0)) >= 1:
        return {}
    target = deficit * float(c["share"])
    # every soldier eating here, cheapest first; own troops before guests of the same rank
    stationed = await tx.conn.fetch("SELECT id, home_id, units FROM stationed WHERE host_id = $1 FOR UPDATE", v.id)
    pool: list[tuple[tuple[float, str], int, str, Any]] = []
    for u, n in (v.state.get("units") or {}).items():
        if n > 0:
            pool.append((rank(game, u), 0, u, None))
    for s in stationed:
        for u, n in s["units"].items():
            if n > 0:
                pool.append((rank(game, u), 1, u, s))
    pool.sort(key=lambda p: (p[0], p[1]))
    dead: dict[int, dict[str, int]] = {}
    freed = 0.0
    changed: dict[int, dict[str, int]] = {}
    for _, _, unit, s in pool:
        if freed >= target or freed >= deficit:
            break
        each = upkeep_of(game, unit)
        have = int(v.state["units"][unit] if s is None else (changed.get(s["id"]) or s["units"])[unit])
        need = max(1, math.ceil((min(target, deficit) - freed) / each)) if each > 0 else have
        n = min(have, need)
        if s is None:
            v.state["units"][unit] = have - n
            home = v.id
        else:
            units = dict(changed.get(s["id"]) or s["units"])
            units[unit] = have - n
            changed[s["id"]] = units
            home = s["home_id"]
        dead.setdefault(home, {})
        dead[home][unit] = dead[home].get(unit, 0) + n
        freed += n * each
    if not dead:
        return {}
    v.state["units"] = {u: n for u, n in v.state["units"].items() if n > 0}
    for sid, units in changed.items():
        left = {u: n for u, n in units.items() if n > 0}
        if left:
            await tx.conn.execute("UPDATE stationed SET units = $2 WHERE id = $1", sid, left)
        else:
            await tx.conn.execute("DELETE FROM stationed WHERE id = $1", sid)
    await save_village(game, tx, v)
    return dead


async def report(game: Game, tx: Tx, v: VillageRow, dead: dict[int, dict[str, int]]) -> None:
    from .villages import push_village

    owners = {r["id"]: r for r in await tx.conn.fetch("SELECT id, name, player_id FROM villages WHERE id = ANY($1::bigint[])", list(dead))}
    for home, units in dead.items():
        o = owners.get(home)
        if o is None:
            continue
        n = sum(units.values())
        where = v.name if home == v.id else f"{v.name} (stationed troops of {o['name']})"
        await add_report(game, tx, o["player_id"], "starvation", f"{n} troops starved in {where}",
                         {"village": v.public(), "home": {"id": home, "name": o["name"]}, "units": units, "resource": food(game)})
    await push_village(game, tx, v)


async def on_tick(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    c, r = cfg(game), food(game)
    if c is None or r is None:
        return
    rows = await tx.conn.fetch("SELECT v.id FROM villages v JOIN players p ON p.id = v.player_id WHERE NOT p.npc ORDER BY v.id")
    now = game.clock.now()
    for row in rows:
        v = await get_village(tx.conn, row["id"])
        extra = await hosted_upkeep(game, tx.conn, v.id)
        state = game.engine.accrue(game.engine.normalize(v.state), now, extra)
        eco = game.engine.economy(state, extra)
        if float(eco["production"].get(r, 0)) >= 0 or float(state["resources"].get(r, 0)) >= 1:
            continue
        v = await get_village(tx.conn, row["id"], lock=True)
        await accrue(game, tx, v)
        dead = await starve(game, tx, v)
        if dead:
            await report(game, tx, v, dead)
    await game.schedule(tx, TICK, now + interval(game), {})


def interval(game: Game) -> int:
    c = cfg(game) or {}
    return max(10_000, int(float(c.get("tick_hours", 1)) * 3_600_000 / game.content.pack["world"]["speed"]))


@hookimpl
async def ovian_started(game: Game) -> None:
    if cfg(game) is None or food(game) is None:
        return
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", TICK):
            await game.schedule(tx, TICK, game.clock.now() + interval(game), {})


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    r = food(game)
    if cfg(game) is None or r is None:
        return
    rate = float(view["economy"]["production"].get(r, 0))
    if rate >= 0:
        return
    stock = float(view["state"]["resources"].get(r, 0))
    soldiers = sum((view["state"].get("units") or {}).values()) + sum(sum(s["units"].values()) for s in view["reinforcements"]["here"])
    view["starvation"] = {
        "resource": r,
        "deficit": round(-rate, 1),
        "starving": stock < 1 and soldiers > 0,
        "empty_at": None if stock < 1 else view["server_time"] + int(stock / -rate * 3_600_000),
        "troops": soldiers,
    }


module = Module("starvation", jobs={TICK: on_tick})
