"""Ver sacrum: a city sends out its young to found a colony.

Every ``every`` levels of the growth building (the civic centre / town hall)
earn a city one ver sacrum. The migrants leave with a cost in resources, travel
to a free settleable tile within ``range_per_level`` × level tiles, and found a
new city there. The colony belongs to the same player, who manages it fully,
and it is also a vassal of its mother city: it pays ``tribute`` of its
production and its culture follows the mother city (see ``submission``).

Configured by the content pack::

    extensions:
      ver_sacrum: { every: 10, range_per_level: 0.5, speed: 6, tribute: 0.1, cost: {...} }
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_player, get_village, own_village, save_village, village_at
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

ARRIVE = "ver_sacrum.arrive"
router = APIRouter(tags=["ver sacrum"])


@dataclass
class Rules:
    every: int = 10
    range_per_level: float = 0.5
    speed: float = 6.0  # tiles per hour at world speed 1
    tribute: float = 0.1
    cost: dict[str, float] = field(default_factory=dict)


def rules(game: Game) -> Rules:
    cfg = game.content.extensions.get("ver_sacrum", {})
    tribute = cfg.get("tribute", game.content.extensions.get("submission", {}).get("tribute", 0.1))
    return Rules(int(cfg.get("every", 10)), float(cfg.get("range_per_level", 0.5)), float(cfg.get("speed", 6.0)),
                 float(tribute), {k: float(v) for k, v in cfg.get("cost", {}).items()})


def growth_level(game: Game, state: dict[str, Any]) -> int:
    """Level of the growth building (civic centre), or of the first starting building."""
    village = game.content.pack["village"]
    building = (village.get("growth") or {}).get("building") or (village["start"]["buildings"] or [{}])[0].get("building")
    return max((s["level"] for s in state["slots"] if s.get("building") == building), default=0)


async def status(game: Game, conn: asyncpg.Connection, v: VillageRow) -> dict[str, Any]:
    r = rules(game)
    level = growth_level(game, v.state)
    earned = level // r.every if r.every > 0 else 0
    used = int(v.meta.get("ver_sacrum_used", 0))
    jobs = await conn.fetch("SELECT id, due_at, payload FROM jobs WHERE kind = $1 AND village_id = $2 ORDER BY due_at", ARRIVE, v.id)
    colonies = await conn.fetch(
        "SELECT id, name, x, y FROM villages WHERE (meta->>'mother_id')::bigint = $1 ORDER BY id", v.id,
    )
    return {
        "level": level,
        "every": r.every,
        "earned": earned,
        "used": used,
        "available": max(0, earned - used),
        "next_at_level": (earned + 1) * r.every,
        "range": level * r.range_per_level,
        "cost": r.cost,
        "speed": r.speed,
        "migrations": [{"id": j["id"], "x": j["payload"]["x"], "y": j["payload"]["y"], "name": j["payload"]["name"],
                        "departs_at": j["payload"]["departs_at"], "arrives_at": j["due_at"]} for j in jobs],
        "colonies": [dict(c) for c in colonies],
    }


class Migration(BaseModel):
    x: int
    y: int
    name: str = Field("", max_length=40)


@router.post("/villages/{village_id}/ver-sacrum")
async def send_migrants(village_id: int, order: Migration, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Send migrants to found a colony at (x, y)."""
    from .villages import push_village, spend

    r = rules(game)
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        st = await status(game, tx.conn, v)
        if st["available"] < 1:
            raise rule("no_ver_sacrum", f"one ver sacrum every {r.every} levels of the city centre")
        distance = math.hypot(order.x - v.x, order.y - v.y)
        if distance > st["range"]:
            raise rule("out_of_range", f"at most {st['range']:g} tiles away")
        tile = game.engine.tiles(order.x, order.y, 1, 1)[0]
        if not tile["settleable"]:
            raise rule("not_settleable", "nobody can live there")
        if await village_at(tx.conn, order.x, order.y):
            raise rule("tile_taken", "a city already stands there")
        if await tx.conn.fetchval(
            "SELECT 1 FROM jobs WHERE kind = $1 AND (payload->>'x')::int = $2 AND (payload->>'y')::int = $3", ARRIVE, order.x, order.y
        ):
            raise rule("tile_taken", "migrants are already on their way there")
        await accrue(game, tx, v)
        if any(v.state["resources"].get(k, 0) < n for k, n in r.cost.items()):
            raise rule("insufficient_resources")
        spend(v, r.cost)
        v.meta["ver_sacrum_used"] = st["used"] + 1
        await save_village(game, tx, v)
        player = await get_player(tx.conn, player_id)
        name = order.name.strip() or f"{player['username']}'s colony"
        now = game.clock.now()
        seconds = max(1.0, distance / r.speed * 3600 / game.content.pack["world"]["speed"])
        await game.schedule(tx, ARRIVE, now + int(seconds * 1000),
                            {"x": order.x, "y": order.y, "name": name, "departs_at": now, "cost": r.cost}, village_id=v.id)
        return await push_village(game, tx, v)


async def on_arrive(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .auth import found_village_at
    from .submission import bind
    from .villages import push_village

    p = job["payload"]
    mother = await get_village(tx.conn, job["village_id"], lock=True)
    colony = await found_village_at(game, tx, mother.player_id, p["name"], p["x"], p["y"])
    if colony is None:
        # someone settled there first: the migrants come home and the ver sacrum can be tried again
        await accrue(game, tx, mother)
        mother.state = game.engine.deposit(mother.state, p.get("cost", {}))
        mother.meta["ver_sacrum_used"] = max(0, int(mother.meta.get("ver_sacrum_used", 0)) - 1)
        await save_village(game, tx, mother)
        data = {"from": mother.public(), "x": p["x"], "y": p["y"], "founded": False}
        await add_report(game, tx, mother.player_id, "ver_sacrum", f"The migrants from {mother.name} found ({p['x']}|{p['y']}) taken", data)
        await push_village(game, tx, mother)
        return
    colony.meta["mother_id"] = mother.id
    await bind(game, tx, colony, mother, rules(game).tribute)
    data = {"from": mother.public(), "colony": colony.public(), "x": p["x"], "y": p["y"], "founded": True}
    await add_report(game, tx, mother.player_id, "ver_sacrum", f"{mother.name} founds {colony.name}", data)
    game.event(tx, mother.player_id, "village.founded", {"village": colony.public(), "mother": mother.public()})
    from .chronicle import record

    await record(game, tx, "colony", f"A ver sacrum from {mother.name} founded {colony.name}", village=colony,
                 data={"mother": mother.public()})
    await push_village(game, tx, await get_village(tx.conn, mother.id))
    await push_village(game, tx, colony)


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    view["ver_sacrum"] = await status(game, conn, village)


module = Module("ver_sacrum", router=router, jobs={ARRIVE: on_arrive})
