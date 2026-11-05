"""Market: merchants carry resources to any city, and players trade through offers.

A city has one merchant per level of its market building; each carries ``carry``
of anything and travels ``speed`` tiles per hour. Merchants are busy while
travelling (there and back) and while an offer of theirs is open.

- ``POST /villages/{id}/market/send`` ships resources to any city (yours or not).
- ``POST /villages/{id}/market/offers`` puts goods on the market for something in return.
- ``POST /market/offers/{offer}/accept`` pays what the offer wants; both shipments set out.

Configured by the content pack::

    extensions:
      market: { building: market, carry: 1000, speed: 12 }
      trade:                       # profit and bandits (optional)
        profit_per_tile: 0.01      # merchants who deliver to another player's city bring home this share of the
        profit_max: 0.25           #   cargo per tile travelled, up to profit_max (same goods, on top of the payment)
        profit_cap_per_level: 2000 # ...but a city earns at most this much a day per market level
        bandits_from: 6            # beyond this many tiles, off the roads, bandits may rob a caravan:
        bandits_per_tile: 0.02     #   chance per tile beyond, up to bandits_max; they take bandits_take of it
        bandits_max: 0.3
        bandits_take: 0.5

Merchants' journeys leave no reports (they would be thousands); a robbery is the exception,
and only for a one-off shipment (routes show it on the route and as an event).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, bump_stat, get_village, lock_villages, own_village, save_village, village_at
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

ARRIVE = "trade.arrive"
RETURN = "trade.return"
router = APIRouter(tags=["market"])


def cfg(game: Game) -> dict[str, Any]:
    c = game.content.extensions.get("market", {})
    return {"building": c.get("building", "market"), "carry": float(c.get("carry", 1000)), "speed": float(c.get("speed", 12))}


def trade_cfg(game: Game) -> dict[str, float] | None:
    c = game.content.extensions.get("trade")
    if c is None:
        return None
    d = {"profit_per_tile": 0.01, "profit_max": 0.25, "profit_cap_per_level": 2000, "bandits_from": 6, "bandits_per_tile": 0.02,
         "bandits_max": 0.3, "bandits_take": 0.5}
    return {k: float(c.get(k, v)) for k, v in d.items()}


def bandit_chance(game: Game, tiles: float, on_road: bool) -> float:
    t = trade_cfg(game)
    if t is None or on_road:
        return 0.0
    return max(0.0, min(t["bandits_max"], t["bandits_per_tile"] * (tiles - t["bandits_from"])))


def day_of(ms: int) -> int:
    return ms // 86_400_000


def profit_room(game: Game, v: VillageRow, now: int) -> float:
    """How much more profit this city may earn today."""
    t = trade_cfg(game)
    if t is None:
        return 0.0
    p = v.meta.get("trade_profit") or {}
    earned = p.get("earned", 0.0) if p.get("day") == day_of(now) else 0.0
    return max(0.0, t["profit_cap_per_level"] * merchants_total(game, v) - earned)


def merchants_total(game: Game, v: VillageRow) -> int:
    b = cfg(game)["building"]
    return max((s["level"] for s in v.state["slots"] if s.get("building") == b), default=0)


async def merchants_busy(conn: asyncpg.Connection, village_id: int) -> int:
    on_road = await conn.fetchval(
        "SELECT coalesce(sum((payload->>'merchants')::int), 0) FROM jobs WHERE kind = ANY($2::text[]) AND (payload->>'home')::bigint = $1",
        village_id, [ARRIVE, RETURN])
    offered = await conn.fetchval("SELECT coalesce(sum(merchants), 0) FROM trade_offers WHERE village_id = $1", village_id)
    return int(on_road) + int(offered)


def clean(resources: dict[str, float], game: Game) -> dict[str, float]:
    known = {r["id"] for r in game.content.pack["resources"]}
    out = {k: math.floor(float(n)) for k, n in resources.items() if n and k in known}
    if any(n < 0 for n in out.values()):
        raise rule("invalid_amount")
    if not out:
        raise rule("nothing_to_send", "choose some resources")
    return out


async def reserve(game: Game, tx: Tx, v: VillageRow, resources: dict[str, float]) -> int:
    """Take resources and check merchants; returns how many merchants carry them."""
    c = cfg(game)
    need = math.ceil(sum(resources.values()) / c["carry"])
    free = merchants_total(game, v) - await merchants_busy(tx.conn, v.id)
    if merchants_total(game, v) == 0:
        raise rule("no_market", "build a market first")
    if need > free:
        raise rule("no_merchants", f"{need} merchants needed, {max(0, free)} free")
    await accrue(game, tx, v)
    if any(v.state["resources"].get(k, 0) < n for k, n in resources.items()):
        raise rule("insufficient_resources")
    for k, n in resources.items():
        v.state["resources"][k] -= n
    return need


async def ship(game: Game, tx: Tx, home: VillageRow, target: VillageRow, resources: dict[str, float], merchants: int, offer: int | None = None,
               route: int | None = None) -> None:
    c = cfg(game)
    seconds = max(1.0, math.hypot(target.x - home.x, target.y - home.y) / c["speed"] * 3600 / game.content.pack["world"]["speed"])
    now = game.clock.now()
    from ..repo import travel_factor

    seconds = max(1.0, seconds * await travel_factor(game, tx.conn, "trade", home, target, now))
    payload = {"home": home.id, "to": target.id, "resources": resources, "merchants": merchants, "departs_at": now,
               "from_name": home.name, "to_name": target.name, "offer": offer, "route": route}
    await game.schedule(tx, ARRIVE, now + int(seconds * 1000), payload, village_id=home.id)
    if target.player_id != home.player_id:
        game.event(tx, target.player_id, "trade.incoming", {"from": home.public(), "to": target.public(), "resources": resources,
                                                            "arrives_at": now + int(seconds * 1000)})


class Shipment(BaseModel):
    x: int
    y: int
    resources: dict[str, float]


@router.post("/villages/{village_id}/market/send")
async def send(village_id: int, body: Shipment, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Ship resources to the city at (x, y)."""
    from .villages import push_village

    resources = clean(body.resources, game)
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        target = await village_at(tx.conn, body.x, body.y)
        if target is None:
            raise not_found("no_village_there")
        if target.id == v.id:
            raise rule("same_village")
        merchants = await reserve(game, tx, v, resources)
        await save_village(game, tx, v)
        await ship(game, tx, v, target, resources, merchants)
        return await push_village(game, tx, v)


async def on_arrive(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    import random

    from .villages import push_village

    p = job["payload"]
    vs = await lock_villages(tx.conn, p["home"], p["to"])
    home, target = vs.get(p["home"]), vs.get(p["to"])
    goods = dict(p["resources"])
    robbed: dict[str, float] = {}
    profit: dict[str, float] = {}
    t = trade_cfg(game)
    if home is not None and target is not None and t is not None:
        tiles = math.hypot(target.x - home.x, target.y - home.y)
        lo, hi = min(home.id, target.id), max(home.id, target.id)
        on_road = bool(await tx.conn.fetchval("SELECT 1 FROM roads WHERE a_id = $1 AND b_id = $2 AND ready_at <= $3", lo, hi, job["due_at"]))
        if random.random() < bandit_chance(game, tiles, on_road):
            robbed = {r: math.floor(n * t["bandits_take"]) for r, n in goods.items()}
            goods = {r: n - robbed[r] for r, n in goods.items()}
        foreign = target.player_id != home.player_id and not await tx.conn.fetchval("SELECT npc FROM players WHERE id = $1", target.player_id)
        if foreign and not robbed:
            share = min(t["profit_max"], t["profit_per_tile"] * tiles)
            room = profit_room(game, home, job["due_at"])
            total = sum(goods.values()) * share
            scale = min(1.0, room / total) if total > 0 else 0.0
            profit = {r: math.floor(n * share * scale) for r, n in goods.items() if math.floor(n * share * scale) > 0}
            if profit:
                day = day_of(job["due_at"])
                prev = home.meta.get("trade_profit") or {}
                earned = (prev.get("earned", 0.0) if prev.get("day") == day else 0.0) + sum(profit.values())
                home.meta["trade_profit"] = {"day": day, "earned": earned}
                await save_village(game, tx, home)
    if target is not None:
        await accrue(game, tx, target, at=job["due_at"])
        target.state = game.engine.deposit(target.state, goods)
        await save_village(game, tx, target)
        await push_village(game, tx, target)
    if home is not None:
        if robbed:
            data = {"from": home.public(), "to": target.public() if target else {"id": p["to"], "name": p["to_name"]}, "robbed": robbed,
                    "delivered": goods}
            game.event(tx, home.player_id, "trade.robbed", data)
            if p.get("route"):
                await tx.conn.execute("UPDATE trade_routes SET last_error = $2 WHERE id = $1", p["route"], "bandits robbed the last caravan")
            else:
                await add_report(game, tx, home.player_id, "trade", f"Bandits robbed your merchants on the way to {p['to_name']}", data)
        back = job["due_at"] + (job["due_at"] - p["departs_at"])
        await game.schedule(tx, RETURN, back, {"home": home.id, "merchants": p["merchants"], "profit": profit}, village_id=home.id)
        await bump_stat(tx.conn, home.player_id, "trades")
        await push_village(game, tx, home)


async def on_return(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    try:
        home = await get_village(tx.conn, job["payload"]["home"], lock=True)
    except Exception:  # noqa: BLE001 - the city is gone
        return
    profit = job["payload"].get("profit") or {}
    if profit:  # what the merchants earned abroad; like loot, it may exceed storage
        await accrue(game, tx, home, at=job["due_at"])
        for r, n in profit.items():
            home.state["resources"][r] = home.state["resources"].get(r, 0) + n
        await save_village(game, tx, home)
        await bump_stat(tx.conn, home.player_id, "trade_profit", sum(profit.values()))
    await push_village(game, tx, home)


# -------------------------------------------------------------------- offers


class Offer(BaseModel):
    give: dict[str, float]
    want: dict[str, float]


@router.post("/villages/{village_id}/market/offers", status_code=201)
async def make_offer(village_id: int, body: Offer, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    give, want = clean(body.give, game), clean(body.want, game)
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        merchants = await reserve(game, tx, v, give)
        await save_village(game, tx, v)
        await tx.conn.execute("INSERT INTO trade_offers(village_id, give, want, merchants, created_at) VALUES ($1, $2, $3, $4, $5)",
                              v.id, give, want, merchants, game.clock.now())
        return await push_village(game, tx, v)


@router.get("/market/offers")
async def offers(game: GameDep, player_id: PlayerId, village_id: int | None = None, limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
    """Open offers, nearest to ``village_id`` first."""
    async with game.pool.acquire() as conn:
        here = await own_village(conn, village_id, player_id) if village_id else None
        rows = await conn.fetch(
            """SELECT o.id, o.give, o.want, o.created_at, v.id AS vid, v.name, v.x, v.y, v.player_id, p.username
               FROM trade_offers o JOIN villages v ON v.id = o.village_id JOIN players p ON p.id = v.player_id ORDER BY o.id DESC LIMIT $1""",
            limit)
        out = [{"id": r["id"], "give": r["give"], "want": r["want"], "created_at": r["created_at"], "mine": r["player_id"] == player_id,
                "village": {"id": r["vid"], "name": r["name"], "x": r["x"], "y": r["y"], "player_id": r["player_id"]}, "player_name": r["username"],
                "distance": round(math.hypot(r["x"] - here.x, r["y"] - here.y), 2) if here else None} for r in rows]
        if here:
            out.sort(key=lambda o: o["distance"])
        return out


@router.post("/market/offers/{offer_id}/accept")
async def accept(offer_id: int, village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Accept an offer from your city ``village_id``: you ship what it wants, and receive what it gives."""
    from .villages import push_village

    async with game.tx() as tx:
        o = await tx.conn.fetchrow("SELECT * FROM trade_offers WHERE id = $1 FOR UPDATE", offer_id)
        if o is None:
            raise not_found("offer_not_found")
        mine = await own_village(tx.conn, village_id, player_id)
        if o["village_id"] == mine.id:
            raise rule("own_offer", "cancel your own offer instead")
        vs = await lock_villages(tx.conn, mine.id, o["village_id"])
        buyer, seller = vs[mine.id], vs[o["village_id"]]
        merchants = await reserve(game, tx, buyer, o["want"])
        await tx.conn.execute("DELETE FROM trade_offers WHERE id = $1", offer_id)
        await save_village(game, tx, buyer)
        await ship(game, tx, buyer, seller, o["want"], merchants, offer=offer_id)
        await ship(game, tx, seller, buyer, o["give"], o["merchants"], offer=offer_id)
        game.event(tx, seller.player_id, "trade.accepted", {"offer": offer_id, "by": buyer.public(), "give": o["give"], "want": o["want"]})
        await push_village(game, tx, seller)
        return await push_village(game, tx, buyer)


@router.delete("/market/offers/{offer_id}")
async def cancel_offer(offer_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    async with game.tx() as tx:
        o = await tx.conn.fetchrow("SELECT * FROM trade_offers WHERE id = $1 FOR UPDATE", offer_id)
        if o is None:
            raise not_found("offer_not_found")
        v = await own_village(tx.conn, o["village_id"], player_id, lock=True)
        await tx.conn.execute("DELETE FROM trade_offers WHERE id = $1", offer_id)
        await accrue(game, tx, v)
        v.state = game.engine.deposit(v.state, o["give"])
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    c = cfg(game)
    total = merchants_total(game, village)
    jobs = await conn.fetch(
        """SELECT kind, due_at, payload FROM jobs WHERE kind = $1 AND ((payload->>'home')::bigint = $2 OR (payload->>'to')::bigint = $2)
           ORDER BY due_at""", ARRIVE, village.id)
    my_offers = await conn.fetch("SELECT id, give, want, merchants, created_at FROM trade_offers WHERE village_id = $1 ORDER BY id", village.id)
    view["market"] = {
        "merchants": total,
        "busy": await merchants_busy(conn, village.id),
        "carry": c["carry"],
        "speed": c["speed"],
        "shipments": [{"outgoing": j["payload"]["home"] == village.id, "from": {"id": j["payload"]["home"], "name": j["payload"]["from_name"]},
                       "to": {"id": j["payload"]["to"], "name": j["payload"]["to_name"]}, "resources": j["payload"]["resources"],
                       "arrives_at": j["due_at"]} for j in jobs],
        "offers": [dict(o) for o in my_offers],
    }
    t = trade_cfg(game)
    if t is not None:
        now = game.clock.now()
        p = village.meta.get("trade_profit") or {}
        view["market"]["trade"] = t | {"profit_today": p.get("earned", 0.0) if p.get("day") == day_of(now) else 0.0,
                                       "profit_cap": t["profit_cap_per_level"] * total}


module = Module("market", router=router, jobs={ARRIVE: on_arrive, RETURN: on_return})
