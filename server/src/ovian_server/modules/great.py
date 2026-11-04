"""Great buildings: anyone may help raise them.

The buildings listed in ``extensions.great_buildings.buildings`` are built as usual
by their owner, and any player (the owner too) can contribute resources from one of
their cities towards the next level. When contributions reach the level's total cost,
the level is finished at once. Other players who contributed get ``reward`` × their
contribution back, spread over the resources, in the city they gave from.

``GET /great-buildings`` lists great buildings near a place, with their progress.
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
from ..repo import VillageRow, accrue, add_report, bump_stat, get_village, lock_villages, own_village, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game

router = APIRouter(tags=["great buildings"])


def great_ids(game: Game) -> list[str]:
    return list(game.content.extensions.get("great_buildings", {}).get("buildings", []))


def level_cost(game: Game, building: str, level: int) -> float:
    return float(sum(game.engine.build_cost(building, level).values()))


async def status(game: Game, conn: asyncpg.Connection, v: VillageRow) -> list[dict[str, Any]]:
    out = []
    for slot, s in enumerate(v.state["slots"]):
        b = s.get("building")
        if b not in great_ids(game) or s["level"] < 1:
            continue
        d = game.content.building(b)
        nxt = s["level"] + 1
        if nxt > d["max_level"]:
            out.append({"building": b, "slot": slot, "level": s["level"], "max_level": d["max_level"], "complete": True})
            continue
        rows = await conn.fetch(
            """SELECT p.id, p.username, sum(g.points) AS points FROM great_contributions g LEFT JOIN players p ON p.id = g.player_id
               WHERE g.village_id = $1 AND g.building = $2 AND g.level = $3 GROUP BY p.id ORDER BY points DESC""", v.id, b, nxt)
        out.append({"building": b, "slot": slot, "level": s["level"], "max_level": d["max_level"], "next_level": nxt,
                    "cost": level_cost(game, b, nxt), "points": float(sum(r["points"] for r in rows)),
                    "contributors": [{"player_id": r["id"], "name": r["username"], "points": float(r["points"])} for r in rows]})
    return out


class Gift(BaseModel):
    from_village_id: int
    resources: dict[str, float]


@router.post("/villages/{village_id}/great/{building}/contribute")
async def contribute(village_id: int, building: str, body: Gift, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Give resources from your city towards the next level of a great building."""
    from .villages import push_village

    if building not in great_ids(game):
        raise not_found("not_a_great_building")
    async with game.tx() as tx:
        donor = await own_village(tx.conn, body.from_village_id, player_id)
        vs = await lock_villages(tx.conn, village_id, donor.id)
        owner, donor = vs.get(village_id), vs[donor.id]
        if owner is None:
            raise not_found("village_not_found")
        st = next((g for g in await status(game, tx.conn, owner) if g["building"] == building), None)
        if st is None:
            raise not_found("not_built")
        if st.get("complete"):
            raise rule("max_level")
        await accrue(game, tx, donor)
        gift = {k: math.floor(float(n)) for k, n in body.resources.items() if n and n > 0 and k in donor.state["resources"]}
        remaining = st["cost"] - st["points"]
        total = sum(gift.values())
        if total <= 0:
            raise rule("nothing_to_send", "choose some resources")
        if total > remaining:  # never take more than the level still needs
            scale = remaining / total
            gift = {k: math.floor(n * scale) for k, n in gift.items()}
            total = sum(gift.values())
        if any(donor.state["resources"].get(k, 0) < n for k, n in gift.items()):
            raise rule("insufficient_resources")
        for k, n in gift.items():
            donor.state["resources"][k] -= n
        await save_village(game, tx, donor)
        nxt = st["next_level"]
        await tx.conn.execute("INSERT INTO great_contributions(village_id, building, level, player_id, points, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
                              owner.id, building, nxt, player_id, total, game.clock.now())
        await bump_stat(tx.conn, player_id, "great_points", total)
        if owner.player_id != player_id:
            game.event(tx, owner.player_id, "great.contribution", {"village": owner.public(), "building": building, "from": donor.public(), "points": total})
        if st["points"] + total >= st["cost"] - 0.5:
            await _raise(game, tx, owner if owner.id != donor.id else donor, building, st["slot"], nxt)
        if owner.id != donor.id:
            await push_village(game, tx, await get_village(tx.conn, owner.id))  # the owner's own view, to the owner
        return await push_village(game, tx, await get_village(tx.conn, donor.id))


async def _raise(game: Game, tx: Any, owner: VillageRow, building: str, slot: int, level: int) -> None:
    reward = float(game.content.extensions.get("great_buildings", {}).get("reward", 0.5))
    owner = await get_village(tx.conn, owner.id, lock=True)
    await accrue(game, tx, owner)
    owner.state = game.engine.complete_build(owner.state, slot, building, level)
    await save_village(game, tx, owner)
    name = game.content.building(building)["name"]
    rows = await tx.conn.fetch(
        """SELECT player_id, sum(points) AS points, (array_agg(created_at ORDER BY id DESC))[1] AS last FROM great_contributions
           WHERE village_id = $1 AND building = $2 AND level = $3 GROUP BY player_id""", owner.id, building, level)
    resources = [r["id"] for r in game.content.pack["resources"]]
    for r in rows:
        if r["player_id"] is None:
            continue
        data = {"village": owner.public(), "building": building, "level": level, "points": float(r["points"])}
        if r["player_id"] != owner.player_id and reward > 0:
            home = await tx.conn.fetchval("SELECT id FROM villages WHERE player_id = $1 ORDER BY id LIMIT 1", r["player_id"])
            if home:
                hv = await get_village(tx.conn, home, lock=True)
                await accrue(game, tx, hv)
                each = math.floor(float(r["points"]) * reward / len(resources))
                hv.state = game.engine.deposit(hv.state, {k: each for k in resources})
                await save_village(game, tx, hv)
                data["reward"] = {k: each for k in resources}
        await add_report(game, tx, r["player_id"], "great", f"{name} of {owner.name} reached level {level}", data)
    await game.emit("ovian_build_completed", game=game, tx=tx, village=owner, building=building, level=level)


@router.get("/great-buildings")
async def nearby(game: GameDep, player_id: PlayerId, x: int, y: int, radius: int = 25) -> list[dict[str, Any]]:
    """Great buildings within ``radius`` tiles of (x, y), nearest first."""
    ids = great_ids(game)
    async with game.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT v.id FROM villages v, jsonb_array_elements(v.state->'slots') s
               WHERE s->>'building' = ANY($1::text[]) AND (s->>'level')::int > 0 AND v.x BETWEEN $2 AND $3 AND v.y BETWEEN $4 AND $5""",
            ids, x - radius, x + radius, y - radius, y + radius)
        out = []
        for r in rows:
            v = await get_village(conn, r["id"])
            owner = await conn.fetchval("SELECT username FROM players WHERE id = $1", v.player_id)
            for g in await status(game, conn, v):
                out.append(g | {"village": v.public(), "owner": owner, "distance": round(math.hypot(v.x - x, v.y - y), 2)})
        return sorted(out, key=lambda g: g["distance"])


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    view["great"] = await status(game, conn, village)


module = Module("great", router=router)
