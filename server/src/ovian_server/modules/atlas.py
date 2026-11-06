"""The atlas: the whole world as GeoJSON, to import into OpenFantasyMap or any GIS.

``GET /atlas.geojson`` draws the world as it is now; ``GET /hall-of-fame/{round}/atlas.geojson`` the world as it was
when that round ended (the snapshot is taken when the admin starts a new round, before the map is wiped). One
FeatureCollection, each feature with a ``layer``:

- ``world``: the boundary of the map, with the world id, round, size and speed;
- ``terrain``: one polygon per tile that isn't plain (water, beach, forest, hills, mountain);
- ``city``: a point per city, with its ruler, people, population, culture, wonder level, alliance, overlord and,
  for barbarian camps and ruins, the camp level and who abandoned it;
- ``road``: a line per road between two cities;
- ``event``: the round's chronicle entries that happened somewhere (battles, foundings, ...), with ``start_date``.

The grid is projected like the chronicle (``extensions.chronicle.geo``: ``lon`` and ``lat`` of the corner of tile
0,0, ``deg_per_tile``, ``real``); cities and events sit at the centre of their tile. Unless the pack maps its grid
onto real ground, every feature carries ``fictional: true``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter

from ..deps import GameDep
from ..errors import not_found
from .base import Module

if TYPE_CHECKING:
    from ..game import Game

router = APIRouter(tags=["chronicle"])


def projection(game: Game) -> tuple[float, float, float, bool]:
    """(lon, lat) of the corner of tile 0,0, degrees per tile, and whether the geography is fictional."""
    geo = game.content.extensions.get("chronicle", {}).get("geo", {})
    return float(geo.get("lon", 12.0)), float(geo.get("lat", 42.0)), float(geo.get("deg_per_tile", 0.05)), not geo.get("real", False)


def _iso(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def _feature(geometry: dict[str, Any], layer: str, **props: Any) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": {"layer": layer, **props}}


async def build(game: Game, conn: asyncpg.Connection, rnd: int) -> dict[str, Any]:
    """The world as a FeatureCollection: boundary, terrain, cities, roads and the round's events."""
    lon0, lat0, d, fictional = projection(game)
    world = game.content.pack["world"]
    w, h = int(world["width"]), int(world["height"])
    wid = game.settings.world_id
    base = {"world": wid, "round": rnd, "fictional": fictional}

    def lon(x: float) -> float:
        return round(lon0 + x * d, 6)

    def lat(y: float) -> float:
        return round(lat0 - y * d, 6)

    def centre(x: int, y: int) -> list[float]:
        return [lon(x + 0.5), lat(y + 0.5)]

    def box(x0: int, y0: int, x1: int, y1: int) -> dict[str, Any]:
        return {"type": "Polygon", "coordinates": [[[lon(x0), lat(y0)], [lon(x1), lat(y0)], [lon(x1), lat(y1)], [lon(x0), lat(y1)], [lon(x0), lat(y0)]]]}

    features = [_feature(box(0, 0, w, h), "world", name=f"Ovian world {wid}", width=w, height=h, speed=world.get("speed"),
                         exported=_iso(game.clock.now()), **base)]
    for y0 in range(0, h, 64):
        for x0 in range(0, w, 64):
            for t in game.engine.tiles(x0, y0, min(64, w - x0), min(64, h - y0)):
                if t["terrain"] != "plain":
                    features.append(_feature(box(t["x"], t["y"], t["x"] + 1, t["y"] + 1), "terrain", terrain=t["terrain"], x=t["x"], y=t["y"], **base))

    wonder = game.content.extensions.get("wonder", {}).get("building", "wonder")
    for v in await conn.fetch(
        """SELECT v.id, v.name, v.x, v.y, v.population, v.culture, v.created_at, v.meta, p.username, p.tribe, p.npc, p.bot,
                  a.tag AS alliance, o.name AS overlord, op.username AS overlord_ruler,
                  (SELECT max((s->>'level')::int) FROM jsonb_array_elements(v.state->'slots') s WHERE s->>'building' = $1) AS wonder
           FROM villages v JOIN players p ON p.id = v.player_id
             LEFT JOIN alliance_members am ON am.player_id = p.id LEFT JOIN alliances a ON a.id = am.alliance_id
             LEFT JOIN vassals s ON s.vassal_id = v.id LEFT JOIN villages o ON o.id = s.overlord_id LEFT JOIN players op ON op.id = o.player_id
           ORDER BY v.id""", wonder):
        meta = v["meta"] or {}
        camp, abandoned = meta.get("camp") or {}, meta.get("abandoned") or {}
        kind = "ruins" if abandoned else "camp" if v["npc"] else "city"
        features.append(_feature({"type": "Point", "coordinates": centre(v["x"], v["y"])}, "city",
                                 name=v["name"], kind=kind, x=v["x"], y=v["y"], ruler=v["username"], people=v["tribe"], ai=bool(v["bot"]),
                                 population=v["population"], culture=round(float(v["culture"] or 0), 1), founded=_iso(v["created_at"]),
                                 start_date=(_iso(v["created_at"]) or "")[:10] or None, wonder=v["wonder"] or 0, alliance=v["alliance"],
                                 overlord=v["overlord"], overlord_ruler=v["overlord_ruler"], camp_level=camp.get("level"),
                                 abandoned_by=abandoned.get("player"), **base))

    for r in await conn.fetch(
        """SELECT r.id, r.ready_at, p.username, a.name AS a_name, a.x AS a_x, a.y AS a_y, b.name AS b_name, b.x AS b_x, b.y AS b_y
           FROM roads r JOIN villages a ON a.id = r.a_id JOIN villages b ON b.id = r.b_id JOIN players p ON p.id = r.player_id ORDER BY r.id"""):
        features.append(_feature({"type": "LineString", "coordinates": [centre(r["a_x"], r["a_y"]), centre(r["b_x"], r["b_y"])]}, "road",
                                 name=f"{r['a_name']} – {r['b_name']}", builder=r["username"], ready=_iso(r["ready_at"]), **base))

    for e in await conn.fetch("SELECT id, kind, title, at, x, y FROM chronicle WHERE round = $1 AND x IS NOT NULL ORDER BY at, id", rnd):
        when = _iso(e["at"]) or ""
        features.append(_feature({"type": "Point", "coordinates": centre(e["x"], e["y"])}, "event",
                                 name=e["title"], kind=e["kind"], x=e["x"], y=e["y"], start_date=when[:10], timestamp=when, **base))

    return {"type": "FeatureCollection", "name": f"Ovian world {wid}, round {rnd}", "features": features}


@router.get("/atlas.geojson")
async def atlas(game: GameDep) -> dict[str, Any]:
    """The world as it is now, as GeoJSON (see the module notes)."""
    from .chronicle import current_round

    async with game.pool.acquire() as conn:
        return await build(game, conn, await current_round(conn))


@router.get("/hall-of-fame/{rnd}/atlas.geojson")
async def past_atlas(rnd: int, game: GameDep) -> dict[str, Any]:
    """The world as it was when that round ended."""
    async with game.pool.acquire() as conn:
        a = await conn.fetchval("SELECT atlas FROM hall_of_fame WHERE round = $1", rnd)
    if a is None:
        raise not_found("atlas_not_found")  # no map was kept for that round
    return a


module = Module("atlas", router=router)
