"""Governments: each player rules all their cities under one constitution.

``extensions.governments``::

    governments:
      default: chiefdom
      anarchy_hours: 6        # between two governments nothing works well
      cooldown_hours: 48      # before you may change again
      anarchy: { contentment: -15, production: { all: -0.1 } }
      list:
        monarchy: { name: Monarchy, text: ..., defense: 0.1, contentment: 5 }

Effects of a government (all optional): ``production`` per resource (``all`` for
every one), ``attack`` and ``defense`` fractions in battle, ``contentment`` points,
``favor`` (more favor from temples), ``trade_speed`` and ``march_speed`` (fractions
faster). Hours are at world speed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import refresh_all
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

router = APIRouter(tags=["governments"])
END = "government.settled"


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("governments", {})


def _ms(game: Game, hours: float) -> int:
    return int(hours * 3_600_000 / game.content.pack["world"]["speed"])


def _cache(game: Game) -> dict[int, dict[str, Any]]:
    return game.__dict__.setdefault("_governments", {})


async def load(game: Game, conn: asyncpg.Connection, player_id: int) -> dict[str, Any]:
    c = _cache(game)
    if player_id not in c:
        m = await conn.fetchval("SELECT meta->'government' FROM players WHERE id = $1", player_id)
        c[player_id] = m or {}
    return c[player_id]


def effects_of(game: Game, g: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(label, effects) of a player's government right now."""
    conf = cfg(game)
    if g.get("anarchy_until", 0) > game.clock.now():
        return "Anarchy", conf.get("anarchy", {"contentment": -15, "production": {"all": -0.1}})
    gid = g.get("id") or conf.get("default")
    gov = conf.get("list", {}).get(gid)
    return (gov["name"], gov) if gov else ("", {})


def effect(game: Game, g: dict[str, Any], key: str) -> float:
    return float(effects_of(game, g)[1].get(key, 0) or 0)


def effect_now(game: Game, player_id: int, key: str) -> float:
    """Synchronous lookup for code that has no connection (favor rates); 0 until the player's government is loaded."""
    return effect(game, _cache(game).get(player_id, {}), key)


@router.get("/me/government")
async def mine(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    conf = cfg(game)
    async with game.pool.acquire() as conn:
        g = await load(game, conn, player_id)
    label, _ = effects_of(game, g)
    now = game.clock.now()
    return {
        "current": g.get("id") or conf.get("default"),
        "label": label,
        "anarchy_until": g.get("anarchy_until", 0) if g.get("anarchy_until", 0) > now else 0,
        "can_change_at": max(now, int(g.get("since", 0)) + _ms(game, float(conf.get("cooldown_hours", 48)))) if g.get("since") else now,
        "anarchy_hours": float(conf.get("anarchy_hours", 6)) / game.content.pack["world"]["speed"],
        "options": [{"id": k} | v for k, v in conf.get("list", {}).items()],
    }


class Choose(BaseModel):
    id: str


@router.post("/me/government")
async def choose(body: Choose, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Change government: a spell of anarchy follows, then the new one takes effect."""
    conf = cfg(game)
    if body.id not in conf.get("list", {}):
        raise not_found("unknown_government")
    now = game.clock.now()
    async with game.tx() as tx:
        await tx.conn.execute("SELECT 1 FROM players WHERE id = $1 FOR UPDATE", player_id)
        _cache(game).pop(player_id, None)
        g = await load(game, tx.conn, player_id)
        if (g.get("id") or conf.get("default")) == body.id:
            raise rule("same_government", "that is your government already")
        if g.get("since") and now < int(g["since"]) + _ms(game, float(conf.get("cooldown_hours", 48))):
            raise rule("government_cooldown", "your people need time before another change")
        from . import gods

        for r in await tx.conn.fetch("SELECT id FROM villages WHERE player_id = $1 FOR UPDATE", player_id):
            from ..repo import get_village

            v = await get_village(tx.conn, r["id"])
            gods.settle(game, v)  # favor so far at the old rate
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        anarchy = now + _ms(game, float(conf.get("anarchy_hours", 6)))
        g = {"id": body.id, "since": now, "anarchy_until": anarchy}
        await tx.conn.execute("UPDATE players SET meta = jsonb_set(meta, '{government}', $2) WHERE id = $1", player_id, g)
        _cache(game)[player_id] = g
        await refresh_all(game, player_id, tx=tx)
        await game.schedule(tx, END, anarchy + 1, {"player_id": player_id})
        name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
        from .chronicle import record

        await record(game, tx, "government", f"{name} proclaims a new government: {conf['list'][body.id]['name']}", player_id=player_id,
                     data={"government": body.id})
    return await mine(player_id, game)


async def on_settled(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    pid = job["payload"]["player_id"]
    _cache(game).pop(pid, None)
    await load(game, tx.conn, pid)
    await refresh_all(game, pid, tx=tx)
    game.event(tx, pid, "government.settled", {"government": _cache(game)[pid].get("id")})


# ---------------------------------------------------------------------- hooks


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.pool.acquire() as conn:
        for r in await conn.fetch("SELECT id, meta->'government' AS g FROM players"):
            _cache(game)[r["id"]] = r["g"] or {}


def _production(game: Game, eff: dict[str, Any]) -> dict[str, float]:
    p = eff.get("production") or {}
    ids = [r["id"] for r in game.content.pack["resources"]]
    out: dict[str, float] = {}
    for k, n in p.items():
        for r in ids if k == "all" else [k]:
            if r in ids:
                out[r] = out.get(r, 0.0) + float(n)
    return out


@hookimpl
async def ovian_production(game: Game, conn: asyncpg.Connection, village: VillageRow) -> dict[str, float]:
    if not cfg(game):
        return {}
    return _production(game, effects_of(game, await load(game, conn, village.player_id))[1])


@hookimpl
async def ovian_contentment(game: Game, conn: asyncpg.Connection, village: VillageRow) -> list[tuple[str, float]]:
    if not cfg(game):
        return []
    label, eff = effects_of(game, await load(game, conn, village.player_id))
    return [(label, float(eff["contentment"]))] if eff.get("contentment") else []


@hookimpl
async def ovian_travel(game: Game, conn: asyncpg.Connection, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
    if not cfg(game):
        return 1.0
    g = await load(game, conn, origin.player_id)
    fast = effect(game, g, "trade_speed" if kind == "trade" else "march_speed")
    return 1.0 / (1.0 + fast) if fast > -1 else 1.0


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    if not cfg(game):
        return
    a = effect(game, await load(game, tx.conn, attacker.player_id), "attack")
    d = effect(game, await load(game, tx.conn, defender.player_id), "defense")
    if a:
        battle["attack_multiplier"] = battle.get("attack_multiplier", 1.0) * (1 + a)
    if d:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
    if a or d:
        battle.setdefault("modifiers", {}).update({k: v for k, v in (("government_attack", a), ("government_defense", d)) if v})


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    if cfg(game):
        g = await load(game, conn, village.player_id)
        label, _ = effects_of(game, g)
        view["government"] = {"id": g.get("id") or cfg(game).get("default"), "label": label,
                              "anarchy_until": g.get("anarchy_until", 0) if g.get("anarchy_until", 0) > game.clock.now() else 0}


module = Module("governments", router=router, jobs={END: on_settled})
