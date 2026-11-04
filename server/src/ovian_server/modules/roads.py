"""Roads between your cities, and trade routes that run by themselves.

**Roads** (``extensions.roads``) link two of your cities, or a city of yours and one
of your vassals. Building one costs ``cost_per_tile`` for each tile of length and
takes ``seconds_per_tile`` per tile (at world speed). Armies, scouts and merchants
travelling between the two ends go ``speed`` times faster. A city may have ``base``
roads, plus one more every ``per_levels`` levels of its growth building (the civic
centre): with the defaults, 1 below level 10, 2 below 20 and so on. Each road is at
most ``max_length`` tiles long. Roads are public and
drawn on the map (``GET /roads``).

**Trade routes** (``extensions.trade_routes``) send the same goods from a city of
yours to any city every ``every_hours``, with the market's merchants. When the goods
or merchants are missing the run is skipped and the route shows why.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import GameError, not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, get_village, own_village, save_village, village_at
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

DONE = "road.done"
RUN = "route.run"
router = APIRouter(tags=["roads and routes"])


def cfg(game: Game) -> dict[str, Any]:
    c = game.content.extensions.get("roads", {})
    return {"cost_per_tile": c.get("cost_per_tile", {}), "seconds_per_tile": float(c.get("seconds_per_tile", 900)),
            "speed": float(c.get("speed", 1.5)), "base": int(c.get("base", 1)), "per_levels": int(c.get("per_levels", 10)),
            "max_length": float(c.get("max_length", 30))}


def max_roads(game: Game, v: VillageRow) -> int:
    """How many roads a city may have: ``base``, plus one every ``per_levels`` levels of its civic centre."""
    from .contentment import growth_level

    c = cfg(game)
    return c["base"] + (growth_level(game, v) // c["per_levels"] if c["per_levels"] > 0 else 0)


def routes_cfg(game: Game) -> dict[str, Any]:
    c = game.content.extensions.get("trade_routes", {})
    return {"max_per_city": int(c.get("max_per_city", 5)), "min_hours": float(c.get("min_hours", 1))}


def length(a: VillageRow, b: VillageRow) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def road_cost(game: Game, tiles: float) -> dict[str, float]:
    return {k: math.ceil(float(n) * tiles) for k, n in cfg(game)["cost_per_tile"].items()}


async def _linked(conn: asyncpg.Connection, a: int, b: int) -> bool:
    lo, hi = min(a, b), max(a, b)
    return bool(await conn.fetchval("SELECT 1 FROM roads WHERE a_id = $1 AND b_id = $2", lo, hi))


async def _yours(conn: asyncpg.Connection, player_id: int, v: VillageRow) -> bool:
    if v.player_id == player_id:
        return True
    return bool(await conn.fetchval(
        "SELECT 1 FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE s.vassal_id = $1 AND o.player_id = $2", v.id, player_id))


class RoadOrder(BaseModel):
    to_id: int


@router.post("/villages/{village_id}/roads", status_code=201)
async def build_road(village_id: int, body: RoadOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    c = cfg(game)
    if not game.content.extensions.get("roads"):
        raise GameError(404, "no_roads", "this world has no roads")
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        other = await get_village(tx.conn, body.to_id)
        if other.id == v.id:
            raise rule("same_village")
        if not await _yours(tx.conn, player_id, other):
            raise rule("not_your_land", "roads join your own cities and your vassals")
        tiles = length(v, other)
        if tiles > c["max_length"]:
            raise rule("road_too_long", f"at most {c['max_length']:g} tiles")
        if await _linked(tx.conn, v.id, other.id):
            raise rule("road_exists")
        for x in (v, other):
            n = await tx.conn.fetchval("SELECT count(*) FROM roads WHERE a_id = $1 OR b_id = $1", x.id)
            cap = max_roads(game, x)
            if n >= cap:
                raise rule("too_many_roads", f"{x.name} may have {cap} road{'s' if cap != 1 else ''}; "
                                             f"one more every {c['per_levels']} levels of its civic centre")
        cost = road_cost(game, tiles)
        await accrue(game, tx, v)
        if any(v.state["resources"].get(k, 0) < n for k, n in cost.items()):
            raise rule("insufficient_resources")
        for k, n in cost.items():
            v.state["resources"][k] -= n
        await save_village(game, tx, v)
        now = game.clock.now()
        ready = now + int(tiles * c["seconds_per_tile"] / game.content.pack["world"]["speed"] * 1000)
        rid = await tx.conn.fetchval("INSERT INTO roads(player_id, a_id, b_id, started_at, ready_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                                     player_id, min(v.id, other.id), max(v.id, other.id), now, ready)
        await game.schedule(tx, DONE, ready, {"road": rid}, village_id=v.id)
        return await push_village(game, tx, v)


@router.delete("/roads/{road_id}")
async def abandon_road(road_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        r = await tx.conn.fetchrow("DELETE FROM roads WHERE id = $1 AND player_id = $2 RETURNING id", road_id, player_id)
        if r is None:
            raise not_found("road_not_found")
        tx.publish(game.topics.map, {"type": "map.road_removed", "at": game.clock.now(), "data": {"id": road_id}})
    return {"id": road_id}


@router.get("/roads")
async def roads(game: GameDep, x: int = 0, y: int = 0, w: int = Query(200, ge=1, le=500), h: int = Query(200, ge=1, le=500)) -> list[dict[str, Any]]:
    """Roads with an end inside the area, finished or being built."""
    rows = await game.pool.fetch(
        """SELECT r.id, r.player_id, r.ready_at, a.id AS aid, a.x AS ax, a.y AS ay, a.name AS an, b.id AS bid, b.x AS bx, b.y AS by, b.name AS bn
           FROM roads r JOIN villages a ON a.id = r.a_id JOIN villages b ON b.id = r.b_id
           WHERE (a.x BETWEEN $1 AND $1 + $3 - 1 AND a.y BETWEEN $2 AND $2 + $4 - 1) OR (b.x BETWEEN $1 AND $1 + $3 - 1 AND b.y BETWEEN $2 AND $2 + $4 - 1)""",
        x, y, w, h)
    now = game.clock.now()
    return [{"id": r["id"], "player_id": r["player_id"], "ready": r["ready_at"] <= now, "ready_at": r["ready_at"],
             "a": {"id": r["aid"], "x": r["ax"], "y": r["ay"], "name": r["an"]}, "b": {"id": r["bid"], "x": r["bx"], "y": r["by"], "name": r["bn"]}}
            for r in rows]


async def on_done(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    r = await tx.conn.fetchrow("SELECT * FROM roads WHERE id = $1", job["payload"]["road"])
    if r is None:
        return
    a, b = await get_village(tx.conn, r["a_id"]), await get_village(tx.conn, r["b_id"])
    game.event(tx, r["player_id"], "road.built", {"id": r["id"], "a": a.public(), "b": b.public()})
    tx.publish(game.topics.map, {"type": "map.road_built", "at": game.clock.now(), "data": {"id": r["id"], "a": a.public(), "b": b.public()}})
    for v in (a, b):
        if v.player_id == r["player_id"]:
            await push_village(game, tx, v)


# ---------------------------------------------------------------- trade routes


class RouteOrder(BaseModel):
    x: int
    y: int
    resources: dict[str, float]
    every_hours: float = Field(gt=0)


@router.post("/villages/{village_id}/routes", status_code=201)
async def add_route(village_id: int, body: RouteOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .market import clean
    from .villages import push_village

    rc = routes_cfg(game)
    if body.every_hours < rc["min_hours"]:
        raise rule("route_too_often", f"at most once every {rc['min_hours']:g} hours")
    resources = clean(body.resources, game)
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        target = await village_at(tx.conn, body.x, body.y)
        if target is None:
            raise not_found("no_village_there")
        if target.id == v.id:
            raise rule("same_village")
        if await tx.conn.fetchval("SELECT count(*) FROM trade_routes WHERE village_id = $1", v.id) >= rc["max_per_city"]:
            raise rule("too_many_routes", f"at most {rc['max_per_city']} routes per city")
        every = int(body.every_hours * 3_600_000 / game.content.pack["world"]["speed"])
        now = game.clock.now()
        rid = await tx.conn.fetchval(
            "INSERT INTO trade_routes(village_id, to_id, resources, every_ms, next_at, created_at) VALUES ($1, $2, $3, $4, $5, $5) RETURNING id",
            v.id, target.id, resources, every, now)
        await game.schedule(tx, RUN, now, {"route": rid}, village_id=v.id)
        return await push_village(game, tx, v)


@router.delete("/routes/{route_id}")
async def drop_route(route_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    async with game.tx() as tx:
        r = await tx.conn.fetchrow("SELECT * FROM trade_routes WHERE id = $1", route_id)
        if r is None:
            raise not_found("route_not_found")
        v = await own_village(tx.conn, r["village_id"], player_id)
        await tx.conn.execute("DELETE FROM trade_routes WHERE id = $1", route_id)
        return await push_village(game, tx, v)


async def on_run(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .market import reserve, ship
    from .villages import push_village

    r = await tx.conn.fetchrow("SELECT * FROM trade_routes WHERE id = $1 FOR UPDATE", job["payload"]["route"])
    if r is None:
        return
    error = None
    try:
        home = await get_village(tx.conn, r["village_id"], lock=True)
        target = await get_village(tx.conn, r["to_id"])
    except GameError:
        await tx.conn.execute("DELETE FROM trade_routes WHERE id = $1", r["id"])
        return
    try:
        async with tx.conn.transaction():  # a failed run must not undo the reschedule
            merchants = await reserve(game, tx, home, r["resources"])
            await save_village(game, tx, home)
            await ship(game, tx, home, target, r["resources"], merchants)
    except GameError as e:
        error = e.code
        home = await get_village(tx.conn, r["village_id"], lock=True)
    nxt = game.clock.now() + r["every_ms"]
    await tx.conn.execute("UPDATE trade_routes SET next_at = $2, last_error = $3 WHERE id = $1", r["id"], nxt, error)
    await game.schedule(tx, RUN, nxt, {"route": r["id"]}, village_id=home.id)
    await push_village(game, tx, home)


# ---------------------------------------------------------------------- hooks


@hookimpl
async def ovian_travel(game: Game, conn: asyncpg.Connection, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
    if not game.content.extensions.get("roads"):
        return 1.0
    lo, hi = min(origin.id, target.id), max(origin.id, target.id)
    if await conn.fetchval("SELECT 1 FROM roads WHERE a_id = $1 AND b_id = $2 AND ready_at <= $3", lo, hi, at):
        return 1.0 / cfg(game)["speed"]
    return 1.0


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    if game.content.extensions.get("roads"):
        rows = await conn.fetch(
            """SELECT r.id, r.ready_at, o.id AS oid, o.name, o.x, o.y, o.player_id FROM roads r
               JOIN villages o ON o.id = CASE WHEN r.a_id = $1 THEN r.b_id ELSE r.a_id END WHERE r.a_id = $1 OR r.b_id = $1 ORDER BY r.id""",
            village.id)
        c = cfg(game)
        view["roads"] = {"speed": c["speed"], "max": max_roads(game, village), "per_levels": c["per_levels"], "max_length": c["max_length"], "cost_per_tile": c["cost_per_tile"],
                         "seconds_per_tile": c["seconds_per_tile"] / game.content.pack["world"]["speed"],
                         "list": [{"id": r["id"], "ready_at": r["ready_at"],
                                   "to": {"id": r["oid"], "name": r["name"], "x": r["x"], "y": r["y"], "player_id": r["player_id"]}} for r in rows]}
    routes = await conn.fetch(
        """SELECT r.*, t.name, t.x, t.y, t.player_id FROM trade_routes r JOIN villages t ON t.id = r.to_id WHERE r.village_id = $1 ORDER BY r.id""",
        village.id)
    view["routes"] = [{"id": r["id"], "to": {"id": r["to_id"], "name": r["name"], "x": r["x"], "y": r["y"], "player_id": r["player_id"]},
                       "resources": r["resources"], "every_ms": r["every_ms"], "next_at": r["next_at"], "last_error": r["last_error"]} for r in routes]


module = Module("roads", router=router, jobs={DONE: on_done, RUN: on_run})
