"""Public world data: content pack, map, players and rankings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..deps import GameDep
from ..errors import not_found

router = APIRouter(tags=["world"])


@router.get("/content")
async def content(game: GameDep) -> dict[str, Any]:
    """The full content pack. Clients feed it to the WebAssembly engine."""
    return game.content.pack


@router.get("/world")
async def world(game: GameDep) -> dict[str, Any]:
    pack = game.content.pack
    return {
        "id": game.settings.world_id,
        "pack": {"id": pack["id"], "name": pack["name"], "version": pack["version"]},
        "speed": pack["world"]["speed"],
        "width": pack["world"]["width"],
        "height": pack["world"]["height"],
        "server_time": game.clock.now(),
        "mqtt_url": game.settings.mqtt_public_url,
        "topic_root": game.topics.root,
    }


@router.get("/map")
async def map_area(
    game: GameDep,
    x: int = 0,
    y: int = 0,
    w: int = Query(20, ge=1, le=64),
    h: int = Query(20, ge=1, le=64),
) -> dict[str, Any]:
    """Terrain and villages in a rectangle. Terrain is procedural, so clients may also compute it locally."""
    assert game.pool is not None
    rows = await game.pool.fetch(
        """SELECT v.id, v.name, v.x, v.y, v.population, v.culture, v.player_id, p.username AS player_name, p.tribe,
                  o.id AS overlord_id, o.name AS overlord_name, o.player_id AS overlord_player_id,
                  op.username AS overlord_player_name, op.tribe AS overlord_tribe,
                  (SELECT count(*) FROM vassals sv WHERE sv.overlord_id = v.id)::int AS vassals,
                  p.protected_until, (p.protected_until > $5 OR p.vacation_until > $5) AS protected, p.vacation_until > $5 AS vacation,
                  p.npc, p.bot, v.meta->'camp'->'level' AS camp_level, a.tag AS alliance_tag, a.id AS alliance_id
           FROM villages v JOIN players p ON p.id = v.player_id
             LEFT JOIN alliance_members am ON am.player_id = p.id LEFT JOIN alliances a ON a.id = am.alliance_id
             LEFT JOIN vassals s ON s.vassal_id = v.id LEFT JOIN villages o ON o.id = s.overlord_id
             LEFT JOIN players op ON op.id = o.player_id
           WHERE v.x >= $1 AND v.x < $1 + $3 AND v.y >= $2 AND v.y < $2 + $4""",
        x, y, w, h, game.clock.now(),
    )
    return {"x": x, "y": y, "w": w, "h": h, "tiles": game.engine.tiles(x, y, w, h), "villages": [dict(r) for r in rows]}


@router.get("/players/{player_id}")
async def player(player_id: int, game: GameDep) -> dict[str, Any]:
    assert game.pool is not None
    p = await game.pool.fetchrow("SELECT id, username, tribe, created_at, protected_until, bot, meta->'government'->>'id' AS government FROM players WHERE id = $1",
                                 player_id)
    if p is None:
        raise not_found("player_not_found")
    villages = await game.pool.fetch("SELECT id, name, x, y, population FROM villages WHERE player_id = $1 ORDER BY id", player_id)
    return dict(p) | {"villages": [dict(v) for v in villages], "population": sum(v["population"] for v in villages)}


@router.get("/rankings")
async def rankings(game: GameDep, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    assert game.pool is not None
    rows = await game.pool.fetch(
        """SELECT p.id, p.username, p.tribe, p.bot, coalesce(sum(v.population), 0)::int AS population, count(v.id)::int AS villages,
                  coalesce(sum(v.culture), 0)::float AS culture,
                  (SELECT count(*) FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE o.player_id = p.id)::int AS vassals
                  , (SELECT a.tag FROM alliance_members am JOIN alliances a ON a.id = am.alliance_id WHERE am.player_id = p.id) AS alliance_tag
           FROM players p LEFT JOIN villages v ON v.player_id = p.id
           WHERE NOT p.npc
           GROUP BY p.id ORDER BY population DESC, p.id LIMIT $1 OFFSET $2""",
        limit, offset,
    )
    return [dict(r) | {"rank": offset + i + 1} for i, r in enumerate(rows)]


from .base import Module  # noqa: E402

module = Module("world", router=router)
