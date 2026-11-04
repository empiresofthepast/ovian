"""Heroes: one per player, chosen from their civilization's heroes.

- A hero lives in one of the player's cities. At home they add ``defense_per_point``
  × defense points to its defense, and ``production_per_point`` × production points
  to its production.
- Sent with an attack or raid (``hero: true``), they add ``attack_per_point`` ×
  attack points to the army's attack. If the whole army falls, the hero dies and
  comes back to life after ``revive`` seconds (at world speed).
- Battles give experience: the value of the enemy troops killed / 100, double
  against barbarian camps. Level L needs ``xp_base`` × L(L+1)/2 experience in
  total; every level gives one point to spend.

Configured by the content pack::

    extensions:
      heroes: { xp_base: 100, attack_per_point: 0.03, defense_per_point: 0.03, production_per_point: 0.02, revive: 14400, speed: 10 }
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, get_player, get_village, own_village, refresh_boost, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

MOVE = "hero.move"
router = APIRouter(tags=["heroes"])


def cfg(game: Game) -> dict[str, float]:
    c = game.content.extensions.get("heroes", {})
    d = {"xp_base": 100, "attack_per_point": 0.03, "defense_per_point": 0.03, "production_per_point": 0.02, "revive": 14400, "speed": 10}
    return {k: float(c.get(k, v)) for k, v in d.items()}


def level_of(game: Game, xp: float) -> int:
    base = cfg(game)["xp_base"]
    return int((math.sqrt(8 * xp / base + 1) - 1) / 2)


def xp_for(game: Game, level: int) -> float:
    return cfg(game)["xp_base"] * level * (level + 1) / 2


def hero_seconds(game: Game, a: tuple[int, int], b: tuple[int, int]) -> float:
    return max(1.0, math.hypot(a[0] - b[0], a[1] - b[1]) / cfg(game)["speed"] * 3600 / game.content.pack["world"]["speed"])


async def load(game: Game, conn: asyncpg.Connection, player_id: int) -> dict[str, Any] | None:
    """The player's hero, brought back to life if their time has come."""
    h = await conn.fetchrow("SELECT * FROM heroes WHERE player_id = $1", player_id)
    if h is None:
        return None
    h = dict(h)
    if h["status"] == "dead" and h["revive_at"] <= game.clock.now():
        await conn.execute("UPDATE heroes SET status = 'home', revive_at = 0 WHERE player_id = $1", player_id)
        h["status"] = "home"
    return h


def view(game: Game, h: dict[str, Any]) -> dict[str, Any]:
    c = cfg(game)
    level = level_of(game, h["xp"])
    p = h["points"]
    return h | {
        "level": level,
        "next_xp": xp_for(game, level + 1),
        "level_xp": xp_for(game, level),
        "unspent": level - sum(p.values()),
        "bonus": {"attack": p.get("attack", 0) * c["attack_per_point"], "defense": p.get("defense", 0) * c["defense_per_point"],
                  "production": p.get("production", 0) * c["production_per_point"]},
    }


def candidates(game: Game, tribe: str) -> list[dict[str, Any]]:
    tribes = game.content.extensions.get("zeroad", {}).get("tribes", {})
    heroes = tribes.get(tribe, {}).get("heroes") or []
    if heroes:
        return heroes
    return [{"id": f"{tribe}_hero_{i}", "name": n, "title": "Hero", "icon": None, "history": ""}
            for i, n in enumerate(("Aristos", "Valeria", "Brennos"))]


@router.get("/hero")
async def get_hero(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Your hero (or null) and, if you have none yet, the heroes you can choose from."""
    async with game.pool.acquire() as conn:
        h = await load(game, conn, player_id)
        player = await get_player(conn, player_id)
        return {"hero": view(game, h) if h else None, "candidates": [] if h else candidates(game, player["tribe"]), "rules": cfg(game)}


class Choose(BaseModel):
    template: str
    village_id: int
    name: str = Field("", max_length=40)


@router.post("/hero", status_code=201)
async def choose(body: Choose, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        if await tx.conn.fetchval("SELECT 1 FROM heroes WHERE player_id = $1", player_id):
            raise rule("hero_exists", "you already have a hero")
        player = await get_player(tx.conn, player_id)
        pick = next((c for c in candidates(game, player["tribe"]) if c["id"] == body.template), None)
        if pick is None:
            raise not_found("unknown_hero")
        v = await own_village(tx.conn, body.village_id, player_id, lock=True)
        await tx.conn.execute("INSERT INTO heroes(player_id, village_id, template, name, created_at) VALUES ($1, $2, $3, $4, $5)",
                              player_id, v.id, pick["id"], body.name.strip() or pick["name"], game.clock.now())
        await refresh_boost(game, tx, v)
        await save_village(game, tx, v)
        return {"hero": view(game, await load(game, tx.conn, player_id))}


class Points(BaseModel):
    attack: int = Field(0, ge=0)
    defense: int = Field(0, ge=0)
    production: int = Field(0, ge=0)


@router.post("/hero/points")
async def spend_points(body: Points, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        h = await load(game, tx.conn, player_id)
        if h is None:
            raise not_found("no_hero")
        unspent = view(game, h)["unspent"]
        add = body.model_dump()
        if sum(add.values()) > unspent:
            raise rule("no_points", f"{unspent} points to spend")
        points = {k: h["points"].get(k, 0) + add[k] for k in ("attack", "defense", "production")}
        await tx.conn.execute("UPDATE heroes SET points = $2 WHERE player_id = $1", player_id, points)
        if add["production"] and h["status"] == "home" and h["village_id"]:
            v = await get_village(tx.conn, h["village_id"], lock=True)
            await refresh_boost(game, tx, v)
            await save_village(game, tx, v)
        return {"hero": view(game, await load(game, tx.conn, player_id))}


class Move(BaseModel):
    village_id: int


@router.post("/hero/move")
async def move(body: Move, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Send the hero to live in another of your cities."""
    async with game.tx() as tx:
        h = await load(game, tx.conn, player_id)
        if h is None:
            raise not_found("no_hero")
        if h["status"] != "home":
            raise rule("hero_busy", "the hero is not at home")
        dest = await own_village(tx.conn, body.village_id, player_id)
        if dest.id == h["village_id"]:
            raise rule("same_village")
        src = await get_village(tx.conn, h["village_id"], lock=True)
        await tx.conn.execute("UPDATE heroes SET status = 'away' WHERE player_id = $1", player_id)
        await refresh_boost(game, tx, src)
        await save_village(game, tx, src)
        due = game.clock.now() + int(hero_seconds(game, src.point, dest.point) * 1000)
        await game.schedule(tx, MOVE, due, {"player_id": player_id, "to": dest.id}, village_id=dest.id)
        return {"hero": view(game, await load(game, tx.conn, player_id)), "arrives_at": due}


async def on_move(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    p = job["payload"]
    v = await get_village(tx.conn, p["to"], lock=True)
    await tx.conn.execute("UPDATE heroes SET status = 'home', village_id = $2 WHERE player_id = $1", p["player_id"], v.id)
    await refresh_boost(game, tx, v)
    await save_village(game, tx, v)
    game.event(tx, p["player_id"], "hero.arrived", {"village": v.public()})


# ------------------------------------------------------------- armies (military)


async def hero_departs(game: Game, tx: Tx, player_id: int, v: VillageRow) -> None:
    h = await load(game, tx.conn, player_id)
    if h is None:
        raise not_found("no_hero")
    if h["status"] != "home" or h["village_id"] != v.id:
        raise rule("hero_busy", "the hero is not at home in this city")
    await tx.conn.execute("UPDATE heroes SET status = 'away' WHERE player_id = $1", player_id)
    await refresh_boost(game, tx, v)


async def hero_returns(game: Game, tx: Tx, home: VillageRow) -> None:
    await tx.conn.execute("UPDATE heroes SET status = 'home', village_id = $2 WHERE player_id = $1 AND status = 'away'", home.player_id, home.id)
    await refresh_boost(game, tx, home)
    await save_village(game, tx, home)
    game.event(tx, home.player_id, "hero.arrived", {"village": home.public()})


def _value(game: Game, losses: dict[str, int]) -> float:
    total = 0.0
    for uid, n in losses.items():
        u = game.content.unit(uid)
        if u:
            total += n * sum(u["cost"].values())
    return total / 100


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    c = cfg(game)
    info: dict[str, Any] = {}
    if battle.get("hero"):
        h = await load(game, tx.conn, attacker.player_id)
        if h:
            bonus = h["points"].get("attack", 0) * c["attack_per_point"]
            battle["attack_multiplier"] = battle.get("attack_multiplier", 1.0) * (1 + bonus)
            info["attacker"] = {"name": h["name"], "template": h["template"], "level": level_of(game, h["xp"]), "attack_bonus": bonus}
    h = await load(game, tx.conn, defender.player_id)
    if h and h["status"] == "home" and h["village_id"] == defender.id:
        bonus = h["points"].get("defense", 0) * c["defense_per_point"]
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + bonus
        info["defender"] = {"name": h["name"], "template": h["template"], "level": level_of(game, h["xp"]), "defense_bonus": bonus}
    battle["heroes"] = info


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    info = battle.get("heroes") or {}
    if not info:
        return
    npc = await tx.conn.fetchval("SELECT npc FROM players WHERE id = $1", defender.player_id)
    killed_def = sum((_value(game, l) for l in result["defender_losses"]), 0.0)
    if "attacker" in info:
        xp = killed_def * (2 if npc else 1)
        await tx.conn.execute("UPDATE heroes SET xp = xp + $2 WHERE player_id = $1", attacker.player_id, xp)
        info["attacker"]["xp"] = round(xp, 1)
        if not result["attacker_survivors"]:
            revive = game.clock.now() + int(cfg(game)["revive"] / game.content.pack["world"]["speed"] * 1000)
            await tx.conn.execute("UPDATE heroes SET status = 'dead', revive_at = $2, village_id = $3 WHERE player_id = $1",
                                  attacker.player_id, revive, attacker.id)
            info["attacker"]["fallen"] = True
            game.event(tx, attacker.player_id, "hero.fallen", {"revive_at": revive})
    if "defender" in info:
        xp = _value(game, result["attacker_losses"])
        await tx.conn.execute("UPDATE heroes SET xp = xp + $2 WHERE player_id = $1", defender.player_id, xp)
        info["defender"]["xp"] = round(xp, 1)
    report["heroes"] = info


@hookimpl
async def ovian_boost(game: Game, conn: asyncpg.Connection, village: VillageRow) -> float:
    h = await conn.fetchrow("SELECT points FROM heroes WHERE village_id = $1 AND status = 'home'", village.id)
    return h["points"].get("production", 0) * cfg(game)["production_per_point"] if h else 0.0


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    h = await conn.fetchrow("SELECT name, template, status FROM heroes WHERE player_id = $1", village.player_id)
    view["hero"] = dict(h) | {"here": bool(await conn.fetchval(
        "SELECT 1 FROM heroes WHERE player_id = $1 AND village_id = $2 AND status = 'home'", village.player_id, village.id))} if h else None


module = Module("heroes", router=router, jobs={MOVE: on_move})
