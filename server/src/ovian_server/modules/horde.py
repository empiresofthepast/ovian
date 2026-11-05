"""The barbarian horde: every so often the barbarians gather against the strongest player.

``extensions.horde``::

    horde:
      every_hours: 24      # real hours between hordes
      warning_hours: 3     # real hours between the alarm and the march (the time others have to send help)
      ratio: 1.0           # horde troops per soldier defending the target city (its own and stationed ones)
      min_troops: 150
      active_days: 3       # only players seen this recently are targets

The target is the player with the largest population who is active and not protected or on
vacation; the horde marches on their most populous city from the nearest barbarian camp. The
whole world is told (chronicle) when it gathers, so neighbours can send reinforcements. Horde
survivors do not stay: whatever they carry off is left in the camp they came from, for anyone
to raid. Throwing the horde back counts as ``hordes_repelled`` for the defender and for every
player whose troops fought in the city.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from ..hooks import hookimpl
from ..repo import VillageRow, bump_stat, get_village, save_village
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

GATHER = "horde.gather"
MISSION = "horde"


def cfg(game: Game) -> dict[str, float] | None:
    c = game.content.extensions.get("horde")
    if c is None:
        return None
    d = {"every_hours": 24, "warning_hours": 3, "ratio": 1.0, "min_troops": 150, "active_days": 3}
    return {k: float(c.get(k, v)) for k, v in d.items()}


async def target_city(game: Game, tx: Tx) -> VillageRow | None:
    c = cfg(game) or {"active_days": 3.0}
    now = game.clock.now()
    pid = await tx.conn.fetchval(
        """SELECT p.id FROM players p JOIN villages v ON v.player_id = p.id
           WHERE NOT p.npc AND NOT p.bot AND p.protected_until <= $1 AND p.vacation_until <= $1
             AND coalesce(p.last_seen_at, p.last_login_at, 0) >= $2
           GROUP BY p.id ORDER BY sum(v.population) DESC, p.id LIMIT 1""",
        now, now - int(c["active_days"] * 86_400_000))
    if pid is None:
        return None
    vid = await tx.conn.fetchval("SELECT id FROM villages WHERE player_id = $1 ORDER BY population DESC, id LIMIT 1", pid)
    return await get_village(tx.conn, vid)


def army(game: Game, size: int, rng: random.Random) -> dict[str, int]:
    from . import pve

    shape = pve.garrison(game, int(pve.cfg(game)["max_level"]), rng)
    total = sum(shape.values()) or 1
    return {u: max(1, math.ceil(n * size / total)) for u, n in shape.items()}


async def gather(game: Game, tx: Tx, rng: random.Random | None = None) -> dict[str, Any] | None:
    """Raise a horde against the strongest player. Returns the movement, or None when there is nobody to march on."""
    from . import pve
    from .chronicle import record
    from .military import dispatch

    c = cfg(game) or {"warning_hours": 3.0, "ratio": 1.0, "min_troops": 150.0}
    rng = rng or random.Random()
    target = await target_city(game, tx)
    if target is None:
        return None
    npc = await pve.npc_id(game, tx.conn)
    camp_id = await tx.conn.fetchval(
        "SELECT id FROM villages WHERE player_id = $1 ORDER BY (x - $2) * (x - $2) + (y - $3) * (y - $3), id LIMIT 1", npc, target.x, target.y)
    if camp_id is None:
        return None
    camp = await get_village(tx.conn, camp_id)
    stationed = await tx.conn.fetch("SELECT units FROM stationed WHERE host_id = $1", target.id)
    defenders = sum((target.state.get("units") or {}).values()) + sum(sum(s["units"].values()) for s in stationed)
    size = int(max(c["min_troops"], c["ratio"] * defenders))
    units = army(game, size, rng)
    depart = game.clock.now() + int(c["warning_hours"] * 3_600_000)
    m = await dispatch(game, tx, "attack", npc, camp, camp, target, units, depart=depart, mission=MISSION)
    owner = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", target.player_id)
    data = {"from": camp.public(), "to": target.public(), "player": owner, "troops": sum(units.values()), "departs_at": depart,
            "arrives_at": m["arrives_at"]}
    game.event(tx, target.player_id, "horde.incoming", data)
    await record(game, tx, "horde", f"A barbarian horde of {sum(units.values())} gathers at {camp.name} against {target.name} of {owner}",
                 village=target, data=data)
    return m


async def on_gather(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await gather(game, tx)
    c = cfg(game)
    if c is not None:
        await game.schedule(tx, GATHER, game.clock.now() + int(c["every_hours"] * 3_600_000), {})


@hookimpl
async def ovian_started(game: Game) -> None:
    c = cfg(game)
    if c is None:
        return
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", GATHER):
            await game.schedule(tx, GATHER, game.clock.now() + int(c["every_hours"] * 3_600_000), {})


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    if battle.get("mission") != MISSION:
        return
    from .chronicle import record

    report["horde"] = True
    if result["attacker_won"]:
        # the horde breaks up: what it carried off is left in its camp, its warriors do not come back
        m = await tx.conn.fetchrow(
            "SELECT id, loot FROM movements WHERE kind = 'return' AND home_id = $1 AND from_id = $2 ORDER BY id DESC LIMIT 1 FOR UPDATE",
            attacker.id, defender.id)
        if m is not None:
            await tx.conn.execute("DELETE FROM jobs WHERE kind = 'movement.arrive' AND (payload->>'movement_id')::bigint = $1", m["id"])
            await tx.conn.execute("DELETE FROM movements WHERE id = $1", m["id"])
            for r, n in (m["loot"] or {}).items():
                attacker.state["resources"][r] = attacker.state["resources"].get(r, 0) + n
            await save_village(game, tx, attacker)
        await record(game, tx, "horde", f"The barbarian horde sacked {defender.name}", village=defender)
        return
    helpers = {r["village"]["player_id"] for r in report["defender"].get("reinforcements", [])}
    for pid in {defender.player_id, *helpers}:
        await bump_stat(tx.conn, pid, "hordes_repelled")
    await record(game, tx, "horde", f"{defender.name} threw back the barbarian horde", village=defender,
                 data={"helpers": len(helpers - {defender.player_id})})


module = Module("horde", jobs={GATHER: on_gather})
