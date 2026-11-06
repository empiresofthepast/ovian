"""World rounds and bans (superusers only).

A round ends when a superuser starts a new one, usually after the wonder victory:

``POST /admin/world/new-round {speed?}``

1. the round goes into the hall of fame: its winner, the leading players and
   alliances, the medal table and how many chronicle entries it left;
2. the world is cleared: cities, armies, trade, vassals, heroes, roads, quests,
   counters and the wonder race (accounts, alliances, achievements, medals, the
   chronicle and chat stay);
3. the round number goes up, the calendar starts again, the world speed changes
   if asked, and every player (not banned) gets a fresh city under beginner protection.

Bans: ``POST /admin/players/{id}/ban {days, reason}`` and ``.../unban``. A banned
player cannot log in or use the API, and leaves no city in the next round.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..content import load_content
from ..deps import GameDep
from ..errors import GameError, not_found, rule
from ..hooks import hookimpl
from .admin import AdminId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game

log = logging.getLogger("ovian.rounds")
router = APIRouter(prefix="/admin", tags=["admin"])

WIPE = [
    "DELETE FROM jobs",
    "DELETE FROM movements",
    "DELETE FROM stationed",
    "DELETE FROM trade_offers",
    "DELETE FROM trade_routes",
    "DELETE FROM roads",
    "DELETE FROM vassals",
    "DELETE FROM dominance",
    "DELETE FROM heroes",
    "DELETE FROM quests_done",
    "DELETE FROM player_stats",
    "DELETE FROM stat_snapshots",
    "DELETE FROM great_contributions",
    "DELETE FROM festival_entries",
    "DELETE FROM reports",
    "DELETE FROM villages",
    "DELETE FROM world_state WHERE key IN ('winner', 'calendar_epoch', 'medal_period', 'festival_results')",
    "UPDATE players SET vacation_until = 0, meta = meta - 'government' - 'effects'",
]


def banned(game: Game) -> dict[int, int]:
    return game.__dict__.setdefault("_banned", {})


def check_ban(game: Game, player_id: int) -> None:
    until = banned(game).get(player_id)
    if until and until > game.clock.now():
        raise GameError(403, "banned", "this account is banned")


class NewRound(BaseModel):
    speed: float | None = Field(None, gt=0, le=1000)


async def apply_speed(game: Game, speed: float | None) -> None:
    if speed and speed != game.content.pack["world"]["speed"]:
        game.content = load_content(game.settings.content_dir, game.pm, speed, game.settings.overrides_file or None)
        log.info("world speed is now %s", speed)


@router.post("/world/new-round")
async def new_round(body: NewRound, admin: AdminId, game: GameDep) -> dict[str, Any]:
    from .auth import found_village
    from .chronicle import current_round, record
    from .medals import _table

    async with game.tx() as tx:
        c = tx.conn
        rnd = await current_round(c)
        winner = await c.fetchval("SELECT value FROM world_state WHERE key = 'winner'")
        top = await c.fetch(
            """SELECT p.id, p.username, p.tribe, count(v.id) AS cities, coalesce(sum(v.population), 0) AS population, coalesce(sum(v.culture), 0) AS culture
               FROM players p JOIN villages v ON v.player_id = p.id WHERE NOT p.npc GROUP BY p.id ORDER BY population DESC LIMIT 10""")
        alliances = await c.fetch(
            """SELECT a.id, a.tag, a.name, count(DISTINCT m.player_id) AS members, coalesce(sum(v.population), 0) AS population
               FROM alliances a JOIN alliance_members m ON m.alliance_id = a.id LEFT JOIN villages v ON v.player_id = m.player_id
               GROUP BY a.id ORDER BY population DESC LIMIT 5""")
        entries = await c.fetchval("SELECT count(*) FROM chronicle WHERE round = $1", rnd)
        started = await c.fetchval("SELECT min(at) FROM chronicle WHERE round = $1", rnd)
        from .victory import titles

        honours = await titles(c, winner)
        data = {"round": rnd, "winner": winner, "titles": honours, "players": [dict(r) for r in top], "alliances": [dict(r) for r in alliances],
                "medals": await _table(c, rnd, 10), "chronicle_entries": entries, "started_at": started,
                "speed": game.content.pack["world"]["speed"]}
        await record(game, tx, "round", f"Round {rnd} ended" + (f": {winner.get('text') or winner['player']['name'] + ' built the wonder'}" if winner else ""), data={"round": rnd})
        for t in honours:
            await record(game, tx, "title", f"{t['player']['name']}: {t['name']} ({t['value']:g} {t['unit']})", player_id=t["player"]["id"],
                         data={"round": rnd, "title": t})
            entry = {"round": rnd, "id": t["id"], "name": t["name"], "value": t["value"], "unit": t["unit"]}
            await c.execute("""UPDATE players SET meta = jsonb_set(meta, '{titles}', coalesce(meta->'titles', '[]'::jsonb) || $2::jsonb)
                               WHERE id = $1""", t["player"]["id"], [entry])
        from .atlas import build

        atlas = await build(game, c, rnd)  # the world as it ends, for OpenFantasyMap and other map tools
        await c.execute("""INSERT INTO hall_of_fame(round, ended_at, data, atlas) VALUES ($1, $2, $3, $4)
                           ON CONFLICT (round) DO UPDATE SET data = $3, ended_at = $2, atlas = $4""", rnd, game.clock.now(), data, atlas)
        for sql in WIPE:
            await c.execute(sql)
        await c.execute("INSERT INTO world_state(key, value) VALUES ('round', to_jsonb($1::int)) ON CONFLICT (key) DO UPDATE SET value = to_jsonb($1::int)",
                        rnd + 1)
        if body.speed:
            await c.execute("INSERT INTO world_state(key, value) VALUES ('speed', to_jsonb($1::float)) ON CONFLICT (key) DO UPDATE SET value = to_jsonb($1::float)",
                            body.speed)
    await apply_speed(game, body.speed)
    game.__dict__.pop("_governments", None)
    await game.emit("ovian_started", game=game)  # calendar, camps, medals and the rest schedule themselves again
    now = game.clock.now()
    founded = 0
    async with game.tx() as tx:
        from ..repo import get_player

        players = await tx.conn.fetch("SELECT id, username FROM players WHERE NOT npc AND banned_until <= $1 ORDER BY id", now)
        for p in players:
            await found_village(game, tx, p["id"], f"{p['username']}'s village")
            player = await get_player(tx.conn, p["id"])
            await game.emit("ovian_player_registered", game=game, tx=tx, player=player)
            founded += 1
        await record(game, tx, "round", f"Round {rnd + 1} began", data={"round": rnd + 1, "players": founded})
        tx.publish(game.topics.server, {"type": "world.new_round", "at": now, "data": {"round": rnd + 1, "speed": game.content.pack["world"]["speed"]}})
    return {"round": rnd + 1, "speed": game.content.pack["world"]["speed"], "players": founded, "archived": data}


class Ban(BaseModel):
    days: float = Field(gt=0, le=3650)
    reason: str = Field("", max_length=500)


@router.post("/players/{pid}/ban")
async def ban(pid: int, body: Ban, admin: AdminId, game: GameDep) -> dict[str, Any]:
    if pid == admin:
        raise rule("ban_yourself", "you cannot ban yourself")
    until = game.clock.now() + int(body.days * 86_400_000)
    r = await game.pool.fetchrow("UPDATE players SET banned_until = $2, ban_reason = $3 WHERE id = $1 AND NOT npc RETURNING id", pid, until, body.reason)
    if r is None:
        raise not_found("player_not_found")
    banned(game)[pid] = until
    return {"id": pid, "banned_until": until, "reason": body.reason}


@router.post("/players/{pid}/unban")
async def unban(pid: int, admin: AdminId, game: GameDep) -> dict[str, Any]:
    await game.pool.execute("UPDATE players SET banned_until = 0, ban_reason = '' WHERE id = $1", pid)
    banned(game).pop(pid, None)
    return {"id": pid, "banned_until": 0}


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.pool.acquire() as conn:
        speed = await conn.fetchval("SELECT (value #>> '{}')::float FROM world_state WHERE key = 'speed'")
        for r in await conn.fetch("SELECT id, banned_until FROM players WHERE banned_until > $1", game.clock.now()):
            banned(game)[r["id"]] = r["banned_until"]
    if speed:  # chosen by a superuser for this round; wins over OVIAN_WORLD_SPEED
        await apply_speed(game, speed)


module = Module("rounds", router=router)
