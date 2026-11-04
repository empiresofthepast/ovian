"""The chronicle: a public history of the world.

Modules call ``record`` for events worth remembering: foundings and colonies,
submissions and rebellions, great battles, wars and pacts, new phases, wonders,
festival winners, governments and the end of a round. Anyone can read it:

- ``GET /chronicle`` lists entries, newest first (``round``, ``kind``, ``before`` a time in ms, ``limit``).
- ``GET /chronicle.geojson`` returns them as a GeoJSON FeatureCollection with
  OpenHistoricalMap-style ``start_date`` properties, ready for a timeline map.

The world grid is projected to longitude and latitude with
``extensions.chronicle.geo`` (``lon``, ``lat`` of tile 0,0 and ``deg_per_tile``).
Unless a pack maps its grid onto real ground (an OFM world), the features carry
``fictional: true`` and must not be uploaded to OpenHistoricalMap as real history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter, Query

from ..deps import GameDep
from ..hooks import hookimpl
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

router = APIRouter(tags=["chronicle"])


async def current_round(conn: asyncpg.Connection) -> int:
    return int(await conn.fetchval("SELECT (value #>> '{}')::int FROM world_state WHERE key = 'round'") or 1)


async def record(game: Game, tx: Tx, kind: str, title: str, *, village: VillageRow | dict[str, Any] | None = None,
                 player_id: int | None = None, data: dict[str, Any] | None = None) -> None:
    """Write an entry; it is also announced on the server topic as ``chronicle.entry``."""
    v = village.public() if hasattr(village, "public") else village  # type: ignore[union-attr]
    now = game.clock.now()
    rnd = await current_round(tx.conn)
    pid = player_id if player_id is not None else (v or {}).get("player_id")
    entry_id = await tx.conn.fetchval(
        """INSERT INTO chronicle(round, at, kind, title, x, y, player_id, village_id, data)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
        rnd, now, kind, title, (v or {}).get("x"), (v or {}).get("y"), pid, (v or {}).get("id"), data or {})
    tx.publish(game.topics.server, {"type": "chronicle.entry", "at": now,
                                    "data": {"id": entry_id, "kind": kind, "title": title, "x": (v or {}).get("x"), "y": (v or {}).get("y")}})


async def player_name(conn: asyncpg.Connection, player_id: int) -> str:
    return await conn.fetchval("SELECT username FROM players WHERE id = $1", player_id) or "?"


async def is_npc(conn: asyncpg.Connection, player_id: int) -> bool:
    return bool(await conn.fetchval("SELECT npc FROM players WHERE id = $1", player_id))


def _row(r: asyncpg.Record) -> dict[str, Any]:
    return {"id": r["id"], "round": r["round"], "at": r["at"], "kind": r["kind"], "title": r["title"], "x": r["x"], "y": r["y"],
            "player": {"id": r["player_id"], "name": r["username"]} if r["player_id"] else None, "village_id": r["village_id"],
            "data": r["data"]}


async def _entries(conn: asyncpg.Connection, rnd: int | None, kind: str | None, before: int | None, limit: int) -> list[asyncpg.Record]:
    if rnd is None:
        rnd = await current_round(conn)
    return await conn.fetch(
        """SELECT c.*, p.username FROM chronicle c LEFT JOIN players p ON p.id = c.player_id
           WHERE c.round = $1 AND ($2::text IS NULL OR c.kind = $2) AND ($3::bigint IS NULL OR c.at < $3)
           ORDER BY c.at DESC, c.id DESC LIMIT $4""", rnd, kind, before, limit)


@router.get("/chronicle")
async def chronicle(game: GameDep, rnd: int | None = Query(None, alias="round"), kind: str | None = None, before: int | None = None,
                    limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    """The history of the world, newest first. Public."""
    async with game.pool.acquire() as conn:
        rows = await _entries(conn, rnd, kind, before, limit)
        kinds = [r["kind"] for r in await conn.fetch("SELECT DISTINCT kind FROM chronicle ORDER BY kind")]
        return {"round": rnd or await current_round(conn), "kinds": kinds, "entries": [_row(r) for r in rows]}


@router.get("/chronicle.geojson")
async def chronicle_geojson(game: GameDep, rnd: int | None = Query(None, alias="round"), kind: str | None = None,
                            limit: int = Query(5000, ge=1, le=20000)) -> dict[str, Any]:
    """The chronicle as GeoJSON points (see the module notes on projection)."""
    geo = game.content.extensions.get("chronicle", {}).get("geo", {})
    lon0, lat0, d = float(geo.get("lon", 12.0)), float(geo.get("lat", 42.0)), float(geo.get("deg_per_tile", 0.05))
    fictional = not geo.get("real", False)
    async with game.pool.acquire() as conn:
        rows = await _entries(conn, rnd, kind, None, limit)
    features = []
    for r in rows:
        if r["x"] is None:
            continue
        when = datetime.fromtimestamp(r["at"] / 1000, tz=timezone.utc)
        e = _row(r)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon0 + r["x"] * d, 6), round(lat0 - r["y"] * d, 6)]},
            "properties": {"name": r["title"], "kind": r["kind"], "start_date": when.date().isoformat(), "timestamp": when.isoformat(),
                           "x": r["x"], "y": r["y"], "round": r["round"], "player": e["player"]["name"] if e["player"] else None,
                           "world": game.settings.world_id, "fictional": fictional},
        })
    return {"type": "FeatureCollection", "name": f"Ovian chronicle, world {game.settings.world_id}", "features": features}


# ------------------------------------------------------------- what gets written


@hookimpl
async def ovian_village_founded(game: Game, tx: Tx, village: VillageRow) -> None:
    if await is_npc(tx.conn, village.player_id):
        return
    name = await player_name(tx.conn, village.player_id)
    mother = village.meta.get("mother_id")
    if mother:
        return  # ver sacrum writes its own entry once the colony is bound
    first = not await tx.conn.fetchval("SELECT 1 FROM villages WHERE player_id = $1 AND id <> $2", village.player_id, village.id)
    await record(game, tx, "founded", f"{name} founded {village.name}" if first else f"{name} founded a new city, {village.name}",
                 village=village)


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    pack = game.content.pack
    growth = (pack["village"].get("growth") or {})
    b = game.content.building(building)
    name = b["name"] if b else building
    if building == growth.get("building"):
        for ph in growth.get("phases", []):
            if ph.get("level") == level and level > 1:
                await record(game, tx, "phase", f"{village.name} entered the {ph.get('name', ph.get('id'))}", village=village,
                             data={"phase": ph.get("id"), "level": level})
    wonder = game.content.extensions.get("wonder", {}).get("building", "wonder")
    great = game.content.extensions.get("great_buildings", {}).get("buildings", [])
    if building == wonder or building in great:
        owner = await player_name(tx.conn, village.player_id)
        verb = "began" if level == 1 else f"raised to level {level}"
        await record(game, tx, "wonder" if building == wonder else "great", f"{owner} {verb} the {name} in {village.name}",
                     village=village, data={"building": building, "level": level})


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    big = float(game.content.extensions.get("chronicle", {}).get("battle_units", 150))
    fought = sum(battle["attackers"].values()) + sum(sum(d.values()) for d in battle["defenders"])
    if fought < big or defender.meta.get("camp"):
        return
    a, d = report["attacker"]["player"]["name"], report["defender"]["player"]["name"]
    won = "defeated" if result["attacker_won"] else "was beaten back by"
    await record(game, tx, "battle", f"Battle of {defender.name}: {a} {won} {d}", village=defender, player_id=attacker.player_id,
                 data={"units": fought, "attacker": report["attacker"]["player"], "defender": report["defender"]["player"],
                       "winner": report["winner"]})


module = Module("chronicle", router=router)
