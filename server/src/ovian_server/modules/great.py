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
    """The great buildings of a city and how the next level is coming along. A level that is funded is under
    construction (``building_level``, ``building_until``); contributions then go to the level after it."""
    from .villages import BUILD

    ids = great_ids(game)
    out = []
    jobs = await conn.fetch("SELECT due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2", v.id, BUILD)
    for slot, s in enumerate(v.state["slots"]):
        b = s.get("building")
        if b not in ids or s["level"] < 1:
            continue
        d = game.content.building(b)
        pending = [j for j in jobs if j["payload"].get("slot") == slot]
        top = max([s["level"], *[j["payload"]["level"] for j in pending]])
        entry: dict[str, Any] = {"building": b, "slot": slot, "level": s["level"], "max_level": d["max_level"]}
        if pending:
            entry["building_level"] = top
            entry["building_until"] = max(j["due_at"] for j in pending)
        nxt = top + 1
        if nxt > d["max_level"]:
            out.append(entry | {"complete": True})
            continue
        rows = await conn.fetch(
            """SELECT p.id, p.username, sum(g.points) AS points FROM great_contributions g LEFT JOIN players p ON p.id = g.player_id
               WHERE g.village_id = $1 AND g.building = $2 AND g.level = $3 GROUP BY p.id ORDER BY points DESC""", v.id, b, nxt)
        out.append(entry | {"next_level": nxt, "cost": level_cost(game, b, nxt), "points": float(sum(r["points"] for r in rows)),
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


def build_seconds(game: Game, state: dict[str, Any], building: str, level: int) -> int:
    """Construction time of a level in this city, as the engine computes it for an ordinary build order."""
    t = game.content.building(building)["time"]
    raw = float(t["base"]) * float(t["factor"]) ** (level - 1)
    build_speed = float(game.engine.economy(state, 0.0)["build_speed"])
    return max(1, round(raw * build_speed / float(game.content.pack["world"]["speed"])))


async def _raise(game: Game, tx: Any, owner: VillageRow, building: str, slot: int, level: int) -> None:
    """The level is funded: construction starts (after whatever is queued on the site) and takes its usual time.
    Contributors from other players get their reward now; the completion itself is the ordinary build job."""
    from .villages import BUILD, build_jobs

    reward = float(game.content.extensions.get("great_buildings", {}).get("reward", 0.5))
    owner = await get_village(tx.conn, owner.id, lock=True)
    await accrue(game, tx, owner)
    now = game.clock.now()
    start = max([now, *[j["due_at"] for j in await build_jobs(tx.conn, owner.id) if j["payload"].get("slot") == slot]])
    seconds = build_seconds(game, owner.state, building, level)
    payload = {"slot": slot, "building": building, "level": level, "cost": {}, "seconds": seconds, "started_at": start, "funded": True}
    await game.schedule(tx, BUILD, start + seconds * 1000, payload, village_id=owner.id)
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
        data["due_at"] = start + seconds * 1000
        await add_report(game, tx, r["player_id"], "great", f"{name} of {owner.name} is being raised to level {level}", data)


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
