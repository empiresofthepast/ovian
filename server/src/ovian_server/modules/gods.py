"""Gods: temples gather favor, which pays for divine powers.

Favor accrues at ``favor_per_level`` × temple level per hour (at world speed),
up to ``max_favor``, and is kept per city. Powers (``extensions.gods.powers``):

- ``boost`` + ``hours``: production bonus in this city for a while.
- ``defense`` + ``hours``: defense bonus in this city for a while.
- ``attack``: the next army from this city to fight gets this attack bonus.
- ``destroy`` with ``target: true``: a foreign city within ``range`` tiles (default
  20) loses that fraction of its stores. Not against protected or vacationing players,
  members of your alliance or its allies.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_village, own_village, refresh_boost, save_village, village_at
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

END = "power.end"
router = APIRouter(tags=["gods"])


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("gods", {})


def temple_level(game: Game, v: VillageRow) -> int:
    b = cfg(game).get("building", "temple")
    return max((s["level"] for s in v.state["slots"] if s.get("building") == b), default=0)


def favor_rate(game: Game, v: VillageRow) -> float:
    from .governments import effect_now

    extra = 1 + effect_now(game, v.player_id, "favor")
    return float(cfg(game).get("favor_per_level", 2)) * temple_level(game, v) * game.content.pack["world"]["speed"] * extra


def favor_now(game: Game, v: VillageRow, now: int) -> float:
    m = v.meta
    have = float(m.get("favor", 0))
    at = int(m.get("favor_at", now))
    return min(float(cfg(game).get("max_favor", 500)), have + favor_rate(game, v) * max(0, now - at) / 3_600_000)


def settle(game: Game, v: VillageRow) -> float:
    """Write the current favor into the (locked) village's meta and return it. Call before the temple changes."""
    now = game.clock.now()
    f = favor_now(game, v, now)
    v.meta["favor"], v.meta["favor_at"] = f, now
    return f


def _hours(game: Game, hours: float) -> int:
    return int(hours * 3_600_000 / game.content.pack["world"]["speed"])


class Cast(BaseModel):
    x: int | None = None
    y: int | None = None


@router.post("/villages/{village_id}/powers/{power}")
async def cast(village_id: int, power: str, body: Cast, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    p = cfg(game).get("powers", {}).get(power)
    if p is None:
        raise not_found("unknown_power")
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        favor = settle(game, v)
        if favor < p["cost"]:
            raise rule("no_favor", f"{p['cost']} favor needed")
        now = game.clock.now()
        if p.get("target"):
            if body.x is None or body.y is None:
                raise rule("no_target", "choose a city")
            target = await village_at(tx.conn, body.x, body.y)
            if target is None:
                raise not_found("no_village_there")
            if target.player_id == player_id:
                raise rule("own_village")
            if math.hypot(target.x - v.x, target.y - v.y) > float(p.get("range", 20)):
                raise rule("out_of_range")
            from .player_rules import shielded

            await shielded(game, tx, player_id, target.player_id)
            target = await get_village(tx.conn, target.id, lock=True)
            await accrue(game, tx, target)
            lost = {k: round(n * float(p["destroy"])) for k, n in target.state["resources"].items()}
            for k, n in lost.items():
                target.state["resources"][k] -= n
            await save_village(game, tx, target)
            data = {"power": power, "name": p["name"], "from": v.public(), "to": target.public(), "lost": lost}
            await add_report(game, tx, target.player_id, "gods", f"{p['name']} struck {target.name}", data)
            await add_report(game, tx, player_id, "gods", f"{p['name']} struck {target.name}", data)
            await push_village(game, tx, target)
        elif "boost" in p:
            v.meta["blessing"] = {"until": now + _hours(game, p.get("hours", 2)), "boost": float(p["boost"])}
            await refresh_boost(game, tx, v)
            await game.schedule(tx, END, v.meta["blessing"]["until"], {"power": power}, village_id=v.id)
        elif "defense" in p:
            v.meta["shield"] = {"until": now + _hours(game, p.get("hours", 2)), "defense": float(p["defense"])}
        elif "attack" in p:
            v.meta["fury"] = float(p["attack"])
        v.meta["favor"] = favor - p["cost"]
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


async def on_end(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    try:
        v = await get_village(tx.conn, job["village_id"], lock=True)
    except Exception:  # noqa: BLE001
        return
    b = v.meta.get("blessing")
    if b and b["until"] <= game.clock.now():
        v.meta.pop("blessing")
    await refresh_boost(game, tx, v)
    await save_village(game, tx, v)


@hookimpl
async def ovian_boost(game: Game, conn: asyncpg.Connection, village: VillageRow) -> float:
    b = village.meta.get("blessing")
    return float(b["boost"]) if b and b["until"] > game.clock.now() else 0.0


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    if building == cfg(game).get("building", "temple"):
        # favor gathered so far was at the old level's rate; settle it and count on from now
        now = game.clock.now()
        rate = float(cfg(game).get("favor_per_level", 2)) * (level - 1) * game.content.pack["world"]["speed"]
        since = int(village.meta.get("favor_at", now))
        have = float(village.meta.get("favor", 0)) + rate * max(0, now - since) / 3_600_000
        village.meta["favor"] = min(float(cfg(game).get("max_favor", 500)), have)
        village.meta["favor_at"] = now
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", village.id, village.meta)


@hookimpl
async def ovian_build_demolished(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    if building == cfg(game).get("building", "temple"):
        # settle the favor gathered while the temple stood; from now on it no longer grows
        slots = village.state["slots"]
        site = next((i for i, s in enumerate(slots) if not s.get("building")), None)
        if site is not None:
            slots[site] = {"building": building, "level": level}
        settle(game, village)
        if site is not None:
            slots[site] = {"building": None, "level": 0}
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", village.id, village.meta)


@hookimpl
async def ovian_village_founded(game: Game, tx: Tx, village: VillageRow) -> None:
    village.meta["favor_at"] = game.clock.now()


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    now = battle.get("at", game.clock.now())
    gods: dict[str, Any] = {}
    s = defender.meta.get("shield")
    if s and s["until"] > now:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + s["defense"]
        gods["shield"] = s["defense"]
    fury = await tx.conn.fetchval("SELECT (meta->>'fury')::float FROM villages WHERE id = $1", attacker.id)
    if fury:
        battle["attack_multiplier"] = battle.get("attack_multiplier", 1.0) * (1 + fury)
        await tx.conn.execute("UPDATE villages SET meta = meta - 'fury' WHERE id = $1", attacker.id)
        attacker.meta.pop("fury", None)
        gods["fury"] = fury
    if gods:
        battle["gods"] = gods


@hookimpl
def ovian_battle_resolved(battle: dict[str, Any], report: dict[str, Any], **_: Any) -> None:
    if battle.get("gods"):
        report["gods"] = battle["gods"]


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    now = game.clock.now()
    m = village.meta
    view["gods"] = {
        "favor": favor_now(game, village, now),
        "favor_at": now,
        "rate": favor_rate(game, village),
        "max": float(cfg(game).get("max_favor", 500)),
        "powers": cfg(game).get("powers", {}),
        "blessing": m.get("blessing") if m.get("blessing", {}).get("until", 0) > now else None,
        "shield": m.get("shield") if m.get("shield", {}).get("until", 0) > now else None,
        "fury": m.get("fury"),
    }


module = Module("gods", router=router, jobs={END: on_end})
