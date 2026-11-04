"""Barbarian camps to raid, and a quest chain that guides new players.

**Camps** belong to a non-player "Barbarians" account. They are spread around the
players' cities (``count`` plus one per five players), each with a level from 1 to
``max_level``: ``troops_per_level`` × level warriors of a random civilization, and
``loot_per_level`` × level of each resource. After a battle they recover in
``regen`` seconds (at world speed). Camps take no part in submission, rankings or
quests for others, and heroes earn double experience there.

**Quests** are listed in ``extensions.quests``; each has a goal and a reward::

    - { id: barracks, title: A place to train, goal: { building: barracks, level: 1 }, reward: { wood: 300 } }

Goals: ``building`` + ``level``, ``units`` (troops at home), ``stat`` + ``value``
(battles_won, camps_beaten, trades, ...), ``culture``, ``villages``, ``vassals``,
``alliance: true``, ``hero_level``. The first ``visible`` quests not yet claimed are shown.

**Tutorial.** Quests may carry a ``hint`` (how to do it) and a ``focus`` telling
clients what to point at: ``{ building: barracks }``, ``{ screen: rally }``... Clients
show the first open quest as a guided step until the player turns the tutorial off
(``POST /me/tutorial {"on": false}``; ``GET /me`` has ``tutorial``).
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, bump_stat, get_village, own_village, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

MAINTAIN = "camps.maintain"
REGEN = "camp.regen"
NPC_NAME = "Barbarians"
router = APIRouter(tags=["camps and quests"])


def cfg(game: Game) -> dict[str, float]:
    c = game.content.extensions.get("camps", {})
    d = {"count": 12, "min_distance": 4, "max_distance": 16, "max_level": 5, "troops_per_level": 12, "regen": 3600, "loot_per_level": 1500}
    return {k: float(c.get(k, v)) for k, v in d.items()}


async def npc_id(game: Game, conn: asyncpg.Connection) -> int:
    pid = await conn.fetchval("SELECT id FROM players WHERE npc AND username = $1", NPC_NAME)
    if pid is None:
        pid = await conn.fetchval(
            "INSERT INTO players(username, password_hash, tribe, created_at, npc) VALUES ($1, '!', 'barbarians', $2, true) RETURNING id",
            NPC_NAME, game.clock.now())
    return pid


def garrison(game: Game, level: int, rng: random.Random) -> dict[str, int]:
    tribes = game.content.tribe_ids()
    tribe = rng.choice(tribes)
    foot = sorted((u for u in game.content.pack["units"] if u["tribe"] == tribe and u["class"] == "infantry"), key=lambda u: sum(u["cost"].values()))
    horse = sorted((u for u in game.content.pack["units"] if u["tribe"] == tribe and u["class"] == "cavalry"), key=lambda u: sum(u["cost"].values()))
    n = int(cfg(game)["troops_per_level"] * level)
    out: dict[str, int] = {}
    if foot:
        out[foot[0]["id"]] = math.ceil(n * 0.6)
        if len(foot) > 1:
            out[foot[min(len(foot) - 1, level // 2)]["id"]] = out.get(foot[min(len(foot) - 1, level // 2)]["id"], 0) + math.ceil(n * 0.25)
    if horse:
        out[horse[0]["id"]] = math.ceil(n * 0.15)
    return out


def stock(game: Game, state: dict[str, Any], level: int, rng: random.Random) -> None:
    state["units"] = garrison(game, level, rng)
    loot = cfg(game)["loot_per_level"] * level
    state["resources"] = {r: loot for r in state["resources"]}


async def maintain(game: Game, tx: Tx) -> int:
    """Found camps until there are enough. Returns how many were founded."""
    from .auth import found_village_at

    c = cfg(game)
    conn = tx.conn
    npc = await npc_id(game, conn)
    players = await conn.fetchval("SELECT count(*) FROM players WHERE NOT npc")
    want = int(c["count"]) + players // 5 if players else 0
    have = await conn.fetchval("SELECT count(*) FROM villages WHERE player_id = $1", npc)
    homes = await conn.fetch("SELECT v.x, v.y FROM villages v JOIN players p ON p.id = v.player_id WHERE NOT p.npc")
    rng = random.Random()
    founded = 0
    for _ in range(int(want - have) * 6):
        if have + founded >= want or not homes:
            break
        h = rng.choice(homes)
        d = rng.uniform(c["min_distance"], c["max_distance"])
        a = rng.uniform(0, 2 * math.pi)
        x, y = round(h["x"] + d * math.cos(a)), round(h["y"] + d * math.sin(a))
        if not game.engine.tiles(x, y, 1, 1)[0]["settleable"]:
            continue
        level = rng.randint(1, int(c["max_level"]))
        v = await found_village_at(game, tx, npc, f"Barbarian camp ({'I II III IV V VI VII VIII IX X'.split()[min(level, 10) - 1]})", x, y)
        if v is None:
            continue
        v.meta["camp"] = {"level": level}
        stock(game, v.state, level, rng)
        await save_village(game, tx, v)
        founded += 1
    return founded


async def on_maintain(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await maintain(game, tx)
    await game.schedule(tx, MAINTAIN, game.clock.now() + 10 * 60_000, {})


async def on_regen(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    try:
        v = await get_village(tx.conn, job["village_id"], lock=True)
    except Exception:  # noqa: BLE001 - the camp is gone
        return
    await accrue(game, tx, v)
    stock(game, v.state, int(v.meta.get("camp", {}).get("level", 1)), random.Random())
    v.meta.pop("regen_at", None)
    await save_village(game, tx, v)


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", MAINTAIN):
            await game.schedule(tx, MAINTAIN, game.clock.now(), {})


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    if result["attacker_won"]:
        await bump_stat(tx.conn, attacker.player_id, "battles_won")
    camp = defender.meta.get("camp")
    if not camp:
        return
    if result["attacker_won"]:
        await bump_stat(tx.conn, attacker.player_id, "camps_beaten")
    report["camp"] = {"level": camp["level"]}
    if not defender.meta.get("regen_at"):
        due = game.clock.now() + int(cfg(game)["regen"] / game.content.pack["world"]["speed"] * 1000)
        defender.meta["regen_at"] = due
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", defender.id, defender.meta)
        await game.schedule(tx, REGEN, due, {}, village_id=defender.id)


# -------------------------------------------------------------------- quests


async def progress(game: Game, conn: asyncpg.Connection, player_id: int, goal: dict[str, Any]) -> tuple[float, float]:
    """(have, need) for a quest goal."""
    if "building" in goal:
        have = await conn.fetchval(
            """SELECT coalesce(max((s->>'level')::int), 0) FROM villages v, jsonb_array_elements(v.state->'slots') s
               WHERE v.player_id = $1 AND s->>'building' = $2""", player_id, goal["building"])
        return float(have), float(goal.get("level", 1))
    if "units" in goal:
        rows = await conn.fetch("SELECT state->'units' AS u FROM villages WHERE player_id = $1", player_id)
        return float(sum(sum(r["u"].values()) for r in rows if r["u"])), float(goal["units"])
    if "stat" in goal:
        v = await conn.fetchval("SELECT value FROM player_stats WHERE player_id = $1 AND stat = $2", player_id, goal["stat"])
        return float(v or 0), float(goal.get("value", 1))
    if "culture" in goal:
        return float(await conn.fetchval("SELECT coalesce(sum(culture), 0) FROM villages WHERE player_id = $1", player_id)), float(goal["culture"])
    if "villages" in goal:
        return float(await conn.fetchval("SELECT count(*) FROM villages WHERE player_id = $1", player_id)), float(goal["villages"])
    if "vassals" in goal:
        n = await conn.fetchval(
            "SELECT count(*) FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN villages v ON v.id = s.vassal_id WHERE o.player_id = $1 AND v.player_id <> $1",
            player_id)
        return float(n), float(goal["vassals"])
    if goal.get("alliance"):
        return float(bool(await conn.fetchval("SELECT 1 FROM alliance_members WHERE player_id = $1", player_id))), 1.0
    if "hero_level" in goal:
        from .heroes import level_of

        xp = await conn.fetchval("SELECT xp FROM heroes WHERE player_id = $1", player_id)
        return float(level_of(game, xp) if xp is not None else 0), float(goal["hero_level"])
    return 0.0, 1.0


def quests(game: Game) -> list[dict[str, Any]]:
    return list(game.content.extensions.get("quests", []))


@router.get("/quests")
async def list_quests(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """The next quests to do, with progress, and how many are done."""
    async with game.pool.acquire() as conn:
        done = {r["quest_id"] for r in await conn.fetch("SELECT quest_id FROM quests_done WHERE player_id = $1", player_id)}
        out = []
        for q in quests(game):
            if q["id"] in done:
                continue
            have, need = await progress(game, conn, player_id, q["goal"])
            out.append(q | {"have": min(have, need), "need": need, "complete": have >= need})
            if len(out) >= int(game.content.extensions.get("quests_visible", 3)):
                break
        meta = await conn.fetchval("SELECT meta FROM players WHERE id = $1", player_id) or {}
        return {"quests": out, "done": len(done), "total": len(quests(game)), "tutorial": not meta.get("tutorial_off", False)}


@router.post("/me/tutorial")
async def tutorial(body: dict[str, bool], player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Turn the guided tutorial on or off: ``{"on": false}``."""
    on = bool(body.get("on", True))
    await game.pool.execute("UPDATE players SET meta = jsonb_set(meta, '{tutorial_off}', to_jsonb($2::boolean)) WHERE id = $1", player_id, not on)
    return {"tutorial": on}


@router.post("/quests/{quest_id}/claim")
async def claim(quest_id: str, village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Collect a finished quest's reward in your city ``village_id``."""
    from .villages import push_village

    q = next((q for q in quests(game) if q["id"] == quest_id), None)
    if q is None:
        raise not_found("quest_not_found")
    async with game.tx() as tx:
        if await tx.conn.fetchval("SELECT 1 FROM quests_done WHERE player_id = $1 AND quest_id = $2", player_id, quest_id):
            raise rule("quest_claimed")
        have, need = await progress(game, tx.conn, player_id, q["goal"])
        if have < need:
            raise rule("quest_unfinished", "not done yet")
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        for k, n in q.get("reward", {}).items():  # rewards may exceed storage, like loot
            v.state["resources"][k] = v.state["resources"].get(k, 0) + n
        await save_village(game, tx, v)
        await tx.conn.execute("INSERT INTO quests_done(player_id, quest_id, at) VALUES ($1, $2, $3)", player_id, quest_id, game.clock.now())
        return await push_village(game, tx, v)


module = Module("pve", router=router, jobs={MAINTAIN: on_maintain, REGEN: on_regen})
