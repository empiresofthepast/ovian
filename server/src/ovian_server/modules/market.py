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


async def ship(game: Game, tx: Tx, home: VillageRow, target: VillageRow, resources: dict[str, float], merchants: int, offer: int | None = None) -> None:
    c = cfg(game)
    seconds = max(1.0, math.hypot(target.x - home.x, target.y - home.y) / c["speed"] * 3600 / game.content.pack["world"]["speed"])
    now = game.clock.now()
    from ..repo import travel_factor

    seconds = max(1.0, seconds * await travel_factor(game, tx.conn, "trade", home, target, now))
    payload = {"home": home.id, "to": target.id, "resources": resources, "merchants": merchants, "departs_at": now,
               "from_name": home.name, "to_name": target.name, "offer": offer}
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
    from .villages import push_village

    p = job["payload"]
    vs = await lock_villages(tx.conn, p["home"], p["to"])
    home, target = vs.get(p["home"]), vs.get(p["to"])
    if target is not None:
        await accrue(game, tx, target, at=job["due_at"])
        target.state = game.engine.deposit(target.state, p["resources"])
        await save_village(game, tx, target)
        data = {"from": {"id": p["home"], "name": p["from_name"]}, "to": target.public(), "resources": p["resources"]}
        await add_report(game, tx, target.player_id, "trade", f"Merchants from {p['from_name']} reached {target.name}", data)
        await push_village(game, tx, target)
    if home is not None:
        if target is not None and target.player_id != home.player_id:
            await add_report(game, tx, home.player_id, "trade", f"Your merchants reached {p['to_name']}", {"from": home.public(), "to": target.public(), "resources": p["resources"]})
        back = job["due_at"] + (job["due_at"] - p["departs_at"])
        await game.schedule(tx, RETURN, back, {"home": home.id, "merchants": p["merchants"]}, village_id=home.id)
        await bump_stat(tx.conn, home.player_id, "trades")
        await push_village(game, tx, home)


async def on_return(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    try:
        home = await get_village(tx.conn, job["payload"]["home"])
    except Exception:  # noqa: BLE001 - the city is gone
        return
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


module = Module("market", router=router, jobs={ARRIVE: on_arrive, RETURN: on_return})
