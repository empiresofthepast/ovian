"""Medals: every period (a week by default) the best players of each category win
gold, silver and bronze, and a hall of fame keeps them.

Categories measure what a player gained during the period:

- ``attacker``: enemy troops killed while attacking or raiding;
- ``defender``: attacking troops killed in your cities;
- ``raider``: resources carried home;
- ``builder``: population gained;
- ``trader``: caravans sent.

``extensions.medals``: ``period_hours`` (real hours, default 168), ``places`` (default 3),
and ``categories`` to rename or drop some. The festival adds ``games_<contest>`` medals.

- ``GET /medals``: the latest awards, the medal table and your own medals.
- ``GET /players/{id}/medals``: anyone's medals.
- ``GET /hall-of-fame``: past rounds, and the all-time medal table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter

from ..deps import GameDep
from ..hooks import hookimpl
from ..repo import VillageRow, bump_stat
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

AWARD = "medals.award"
router = APIRouter(tags=["medals"])

CATEGORIES: dict[str, dict[str, str]] = {
    "attacker": {"name": "Attacker of the week", "stat": "attack_points", "unit": "troops slain"},
    "defender": {"name": "Defender of the week", "stat": "defense_points", "unit": "attackers slain"},
    "raider": {"name": "Raider of the week", "stat": "loot", "unit": "resources carried off"},
    "builder": {"name": "Builder of the week", "stat": "population", "unit": "people gained"},
    "trader": {"name": "Trader of the week", "stat": "trades", "unit": "caravans"},
}


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("medals", {})


def categories(game: Game) -> dict[str, dict[str, str]]:
    custom = cfg(game).get("categories")
    if custom is None:
        return CATEGORIES
    return {k: CATEGORIES.get(k, {}) | (v or {}) for k, v in custom.items()}


def period_ms(game: Game) -> int:
    return int(float(cfg(game).get("period_hours", 168)) * 3_600_000)


async def current(conn: asyncpg.Connection) -> tuple[int, int]:
    from .chronicle import current_round

    rnd = await current_round(conn)
    period = await conn.fetchval("SELECT (value #>> '{}')::int FROM world_state WHERE key = 'medal_period'")
    return rnd, int(period or 1)


async def stats_now(conn: asyncpg.Connection) -> dict[tuple[int, str], float]:
    out: dict[tuple[int, str], float] = {}
    for r in await conn.fetch("SELECT s.player_id, s.stat, s.value FROM player_stats s JOIN players p ON p.id = s.player_id WHERE NOT p.npc"):
        out[(r["player_id"], r["stat"])] = float(r["value"])
    for r in await conn.fetch(
            "SELECT v.player_id, sum(v.population) AS pop FROM villages v JOIN players p ON p.id = v.player_id WHERE NOT p.npc GROUP BY v.player_id"):
        out[(r["player_id"], "population")] = float(r["pop"])
    return out


async def snapshot(conn: asyncpg.Connection, now: dict[tuple[int, str], float]) -> None:
    await conn.execute("DELETE FROM stat_snapshots")
    if now:
        await conn.executemany("INSERT INTO stat_snapshots(player_id, stat, value) VALUES ($1, $2, $3)",
                               [(p, s, v) for (p, s), v in now.items()])


async def award(game: Game, tx: Tx) -> list[dict[str, Any]]:
    """Hand out the medals for the period that just ended and start the next one."""
    conn = tx.conn
    rnd, period = await current(conn)
    now_stats = await stats_now(conn)
    before = {(r["player_id"], r["stat"]): float(r["value"]) for r in await conn.fetch("SELECT * FROM stat_snapshots")}
    places = int(cfg(game).get("places", 3))
    won: list[dict[str, Any]] = []
    players = {p for p, _ in now_stats}
    for cid, c in categories(game).items():
        gains = sorted(((now_stats.get((p, c["stat"]), 0.0) - before.get((p, c["stat"]), 0.0), p) for p in players), reverse=True)
        for rank, (gain, p) in enumerate([g for g in gains if g[0] > 0][:places], start=1):
            await conn.execute("INSERT INTO medals(player_id, round, period, category, rank, value, at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                               p, rnd, period, cid, rank, gain, game.clock.now())
            won.append({"player_id": p, "category": cid, "rank": rank, "value": gain})
            game.event(tx, p, "medal.won", {"category": cid, "name": c.get("name", cid), "rank": rank, "value": gain, "period": period})
    await snapshot(conn, now_stats)
    await conn.execute("INSERT INTO world_state(key, value) VALUES ('medal_period', to_jsonb($1::int)) ON CONFLICT (key) DO UPDATE SET value = to_jsonb($1::int)",
                       period + 1)
    tx.publish(game.topics.server, {"type": "medals.awarded", "at": game.clock.now(), "data": {"round": rnd, "period": period, "medals": len(won)}})
    return won


async def on_award(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await award(game, tx)
    await game.schedule(tx, AWARD, game.clock.now() + period_ms(game), {})


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", AWARD):
            if not await tx.conn.fetchval("SELECT 1 FROM stat_snapshots LIMIT 1"):
                await snapshot(tx.conn, await stats_now(tx.conn))
            await game.schedule(tx, AWARD, game.clock.now() + period_ms(game), {})


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    slain = sum(sum(d.values()) for d in result["defender_losses"])
    lost = sum(result["attacker_losses"].values())
    if slain:
        await bump_stat(tx.conn, attacker.player_id, "attack_points", slain)
    if lost and not defender.meta.get("camp"):
        await bump_stat(tx.conn, defender.player_id, "defense_points", lost)
    loot = sum((report.get("loot") or {}).values())
    if loot:
        await bump_stat(tx.conn, attacker.player_id, "loot", loot)


def _name(game: Game, cid: str) -> str:
    if cid.startswith("games_"):
        c = game.content.extensions.get("festival", {}).get("contests", {}).get(cid[6:], {})
        return c.get("name", cid[6:])
    return categories(game).get(cid, {}).get("name", cid)


async def _table(conn: asyncpg.Connection, rnd: int | None, limit: int = 20) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """SELECT m.player_id, p.username, count(*) FILTER (WHERE rank = 1) AS gold, count(*) FILTER (WHERE rank = 2) AS silver,
                  count(*) FILTER (WHERE rank = 3) AS bronze
           FROM medals m JOIN players p ON p.id = m.player_id WHERE ($1::int IS NULL OR m.round = $1)
           GROUP BY m.player_id, p.username ORDER BY gold DESC, silver DESC, bronze DESC, p.username LIMIT $2""", rnd, limit)
    return [dict(r) for r in rows]


def _medal(game: Game, r: asyncpg.Record) -> dict[str, Any]:
    return {"category": r["category"], "name": _name(game, r["category"]), "rank": r["rank"], "value": r["value"], "round": r["round"],
            "period": r["period"], "at": r["at"], "player": {"id": r["player_id"], "name": r["username"]}}


@router.get("/medals")
async def medals(game: GameDep, player_id: PlayerId) -> dict[str, Any]:
    async with game.pool.acquire() as conn:
        rnd, period = await current(conn)
        latest = await conn.fetch(
            """SELECT m.*, p.username FROM medals m JOIN players p ON p.id = m.player_id
               WHERE m.round = $1 AND m.period = (SELECT max(period) FROM medals WHERE round = $1 AND category NOT LIKE 'games\\_%')
                 AND m.category NOT LIKE 'games\\_%' ORDER BY m.category, m.rank""", rnd)
        mine = await conn.fetch("SELECT m.*, p.username FROM medals m JOIN players p ON p.id = m.player_id WHERE m.player_id = $1 ORDER BY m.id DESC LIMIT 100",
                                player_id)
        due = await conn.fetchval("SELECT min(due_at) FROM jobs WHERE kind = $1", AWARD)
        now = await stats_now(conn)
        before = {(r["player_id"], r["stat"]): float(r["value"]) for r in await conn.fetch("SELECT * FROM stat_snapshots WHERE player_id = $1", player_id)}
        return {
            "round": rnd, "period": period, "next_award_at": due,
            "categories": [{"id": k, "progress": now.get((player_id, c["stat"]), 0.0) - before.get((player_id, c["stat"]), 0.0)} | c
                           for k, c in categories(game).items()],
            "latest": [_medal(game, r) for r in latest],
            "table": await _table(conn, rnd),
            "mine": [_medal(game, r) for r in mine],
        }


@router.get("/players/{pid}/medals")
async def player_medals(pid: int, game: GameDep) -> list[dict[str, Any]]:
    async with game.pool.acquire() as conn:
        rows = await conn.fetch("SELECT m.*, p.username FROM medals m JOIN players p ON p.id = m.player_id WHERE m.player_id = $1 ORDER BY m.id DESC", pid)
        return [_medal(game, r) for r in rows]


@router.get("/hall-of-fame")
async def hall_of_fame(game: GameDep) -> dict[str, Any]:
    """Finished rounds, newest first, and the all-time medal table."""
    async with game.pool.acquire() as conn:
        rounds = await conn.fetch("SELECT round, ended_at, data, atlas IS NOT NULL AS atlas FROM hall_of_fame ORDER BY round DESC")
        from .chronicle import current_round

        return {"current_round": await current_round(conn), "rounds": [dict(r) for r in rounds], "all_time": await _table(conn, None, 50)}


module = Module("medals", router=router, jobs={AWARD: on_award})
