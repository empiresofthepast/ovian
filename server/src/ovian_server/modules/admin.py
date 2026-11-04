"""Superuser views: who has connected, who is online, and which cities they hold.

Superusers are players with ``players.is_admin``; names listed in
``OVIAN_ADMIN_USERS`` are promoted at startup and on login.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from ..deps import GameDep
from ..errors import forbidden
from ..presence import ONLINE_MS
from ..security import current_player_id
from .base import Module

router = APIRouter(prefix="/admin", tags=["admin"])


async def current_admin_id(request: Request, player_id: Annotated[int, Depends(current_player_id)]) -> int:
    game = request.app.state.game
    if not await game.pool.fetchval("SELECT is_admin FROM players WHERE id = $1", player_id):
        raise forbidden("admin_only")
    return player_id


AdminId = Annotated[int, Depends(current_admin_id)]


@router.get("/players")
async def players(_: AdminId, game: GameDep) -> dict[str, Any]:
    """Every player with login and presence data and their cities.

    - ``online``: seen in the last few minutes (API call, MQTT connection or heartbeat).
    - ``connected``: has logged in at least once since tracking began. Players
      from before that only show ``last_seen_at`` once they come back.
    - ``own_cities``: cities that are not vassals of another city.
    """
    await game.presence.flush()
    now = game.clock.now()
    rows = await game.pool.fetch(
        """SELECT id, username, tribe, created_at, protected_until, is_admin, last_login_at, last_seen_at, logins, bot, banned_until, ban_reason
           FROM players WHERE NOT npc ORDER BY coalesce(last_seen_at, 0) DESC, id"""
    )
    cities = await game.pool.fetch(
        """SELECT v.id, v.player_id, v.name, v.x, v.y, v.population, v.culture,
                  o.id AS overlord_id, o.name AS overlord_name, op.username AS overlord_player,
                  (SELECT count(*) FROM vassals sv WHERE sv.overlord_id = v.id)::int AS vassals
           FROM villages v LEFT JOIN vassals s ON s.vassal_id = v.id
             LEFT JOIN villages o ON o.id = s.overlord_id LEFT JOIN players op ON op.id = o.player_id
           WHERE v.player_id IN (SELECT id FROM players WHERE NOT npc)
           ORDER BY v.id"""
    )
    by_player: dict[int, list[dict[str, Any]]] = {}
    for c in cities:
        by_player.setdefault(c["player_id"], []).append({k: c[k] for k in c.keys() if k != "player_id"})
    out = []
    for r in rows:
        mine = by_player.get(r["id"], [])
        out.append(dict(r) | {
            "online": bool(r["last_seen_at"] and now - r["last_seen_at"] <= ONLINE_MS),
            "connected": r["logins"] > 0,
            "protected": r["protected_until"] > now,
            "banned": r["banned_until"] > now,
            "cities": mine,
            "own_cities": sum(1 for c in mine if c["overlord_id"] is None),
            "population": sum(c["population"] for c in mine),
        })
    from .chronicle import current_round

    async with game.pool.acquire() as conn:
        rnd = await current_round(conn)
        winner = await conn.fetchval("SELECT value FROM world_state WHERE key = 'winner'")
    return {
        "server_time": now,
        "online_window_ms": ONLINE_MS,
        "world": {"round": rnd, "speed": game.content.pack["world"]["speed"], "winner": winner},
        "totals": {
            "players": len(out),
            "online": sum(p["online"] for p in out),
            "connected": sum(p["connected"] for p in out),
            "with_own_city": sum(p["own_cities"] > 0 for p in out),
            "cities": len(cities),
            "vassal_cities": sum(c["overlord_id"] is not None for c in cities),
        },
        "players": out,
    }


@router.get("/villages/{village_id}")
async def inspect_village(village_id: int, _: AdminId, game: GameDep) -> dict[str, Any]:
    """Any city's full view, as its owner sees it, plus ``owner``. Read-only: orders still need the owner."""
    from ..repo import get_village
    from .villages import village_view

    async with game.pool.acquire() as conn:
        v = await get_village(conn, village_id)
        owner = await conn.fetchrow("SELECT id, username, tribe, npc FROM players WHERE id = $1", v.player_id)
        return await village_view(game, conn, v) | {"owner": {"id": owner["id"], "name": owner["username"], "tribe": owner["tribe"], "npc": owner["npc"]}}


module = Module("admin", router=router)
