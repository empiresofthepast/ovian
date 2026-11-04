"""Rules about players and the world: vacation, night defense, troop ranks, achievements and the Wonder victory.

- **Vacation** (``extensions.vacation``): ``POST /me/vacation {hours}`` shields every
  city of the player from attacks, raids, scouting and divine wrath, and freezes the
  player's own orders. It lasts ``min_hours`` to ``max_days``; it can be ended after
  ``min_hours``.
- **Night** (``extensions.night``): battles between ``start`` and ``end`` o'clock
  (server time, UTC) give the defender ``defense`` extra.
- **Ranks** (``extensions.ranks``): techs that make a city's troops better soldiers,
  each adding its fraction to attack (when attacking) and defense (when defending).
- **Achievements**: unlocked from player counters and state, announced as
  ``achievement.unlocked`` and listed at ``GET /achievements``.
- **Wonder** (``extensions.wonder``): the first player to finish the last level of
  the wonder building wins the world. ``GET /world/victory`` shows the winner and the
  wonder race; the server topic carries ``world.won``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import rule
from ..hooks import hookimpl
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

router = APIRouter(tags=["players"])


def ext(game: Game, key: str) -> dict[str, Any]:
    return game.content.extensions.get(key, {})


async def shielded(game: Game, tx: Tx, player_id: int, target_player: int) -> None:
    """Refuse a hostile act against a protected, vacationing or friendly player."""
    from .alliances import relation

    now = game.clock.now()
    p = await tx.conn.fetchrow("SELECT protected_until, vacation_until FROM players WHERE id = $1", target_player)
    if p and p["protected_until"] > now:
        raise rule("target_protected", "this player is under beginner protection")
    if p and p["vacation_until"] > now:
        raise rule("target_on_vacation", "this player is on vacation")
    rel = await relation(tx.conn, player_id, target_player)
    if rel == "member":
        raise rule("same_alliance")
    if rel in ("ally", "nap"):
        raise rule("pact")


# ------------------------------------------------------------------ vacation


class Vacation(BaseModel):
    hours: float = Field(gt=0)


@router.post("/me/vacation")
async def start_vacation(body: Vacation, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    c = ext(game, "vacation")
    lo, hi = float(c.get("min_hours", 12)), float(c.get("max_days", 14)) * 24
    if not lo <= body.hours <= hi:
        raise rule("vacation_length", f"between {lo:g} hours and {hi / 24:g} days")
    async with game.tx() as tx:
        if await tx.conn.fetchval("SELECT 1 FROM movements WHERE player_id = $1 AND kind IN ('attack', 'raid', 'scout')", player_id):
            raise rule("armies_away", "wait for your armies to come home")
        now = game.clock.now()
        until = now + int(body.hours * 3_600_000)
        await tx.conn.execute("UPDATE players SET vacation_until = $2, meta = jsonb_set(meta, '{vacation_from}', to_jsonb($3::bigint)) WHERE id = $1",
                              player_id, until, now)
        return {"vacation_until": until}


@router.post("/me/vacation/end")
async def end_vacation(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        p = await tx.conn.fetchrow("SELECT vacation_until, meta FROM players WHERE id = $1", player_id)
        now = game.clock.now()
        since = int(p["meta"].get("vacation_from", 0))
        if p["vacation_until"] > now and now - since < float(ext(game, "vacation").get("min_hours", 12)) * 3_600_000:
            raise rule("vacation_too_short", "a vacation lasts at least its minimum")
        await tx.conn.execute("UPDATE players SET vacation_until = 0 WHERE id = $1", player_id)
        return {"vacation_until": 0}


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    now = game.clock.now()
    mine = await tx.conn.fetchval("SELECT vacation_until FROM players WHERE id = $1", player["id"])
    if mine and mine > now:
        raise rule("on_vacation", "you are on vacation")
    if order["type"] == "send" and order["kind"] in ("attack", "raid", "scout"):
        theirs = await tx.conn.fetchval("SELECT vacation_until FROM players WHERE id = $1", order["target"]["player_id"])
        if theirs and theirs > now:
            raise rule("target_on_vacation", "this player is on vacation")


# ------------------------------------------------------------ night and ranks


def is_night(game: Game, at: int) -> bool:
    c = ext(game, "night")
    if not c:
        return False
    hour = datetime.fromtimestamp(at / 1000, tz=timezone.utc).hour
    start, end = int(c.get("start", 0)), int(c.get("end", 6))
    return start <= hour < end if start <= end else hour >= start or hour < end


def rank_bonus(game: Game, state: dict[str, Any]) -> float:
    ranks = ext(game, "ranks")
    return sum(float(ranks[t]) for t in state.get("techs", []) if t in ranks)


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    extra: dict[str, Any] = {}
    at = battle.get("at", game.clock.now())
    if is_night(game, at):
        d = float(ext(game, "night").get("defense", 0.25))
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
        extra["night"] = d
    a = rank_bonus(game, attacker.state)
    if a:
        battle["attack_multiplier"] = battle.get("attack_multiplier", 1.0) * (1 + a)
        extra["attacker_rank"] = a
    d = rank_bonus(game, defender.state)
    if d:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
        extra["defender_rank"] = d
    if extra:
        battle.setdefault("modifiers", {}).update(extra)


@hookimpl
def ovian_battle_resolved(battle: dict[str, Any], report: dict[str, Any], **_: Any) -> None:
    if battle.get("modifiers"):
        report["modifiers"] = battle["modifiers"]


# -------------------------------------------------------------- achievements

ACHIEVEMENTS: list[dict[str, Any]] = [
    {"id": "first_blood", "name": "First blood", "description": "Win a battle.", "stat": "battles_won", "value": 1},
    {"id": "warlord", "name": "Warlord", "description": "Win 50 battles.", "stat": "battles_won", "value": 50},
    {"id": "barbarian_bane", "name": "Bane of the barbarians", "description": "Beat 10 barbarian camps.", "stat": "camps_beaten", "value": 10},
    {"id": "merchant", "name": "Merchant prince", "description": "Send 20 caravans.", "stat": "trades", "value": 20},
    {"id": "patron", "name": "Patron of the arts", "description": "Give 10,000 resources to great buildings.", "stat": "great_points", "value": 10_000},
    {"id": "overlord", "name": "Overlord", "description": "Hold a foreign city as your vassal.", "check": "vassals", "value": 1},
    {"id": "founder", "name": "Founder", "description": "Found a colony with a ver sacrum.", "check": "villages", "value": 2},
    {"id": "city", "name": "A true city", "description": "Raise a city centre to level 10.", "check": "growth", "value": 10},
    {"id": "metropolis", "name": "Metropolis", "description": "Raise a city centre to level 20.", "check": "growth", "value": 20},
    {"id": "scholar", "name": "Scholar", "description": "Research 5 technologies in one city.", "check": "techs", "value": 5},
    {"id": "sworn", "name": "Sworn brothers", "description": "Join an alliance.", "check": "alliance", "value": 1},
    {"id": "legend", "name": "Living legend", "description": "Bring a hero to level 5.", "check": "hero_level", "value": 5},
    {"id": "wonder", "name": "Wonder of the world", "description": "Begin a wonder.", "check": "wonder", "value": 1},
]


async def _measure(game: Game, conn: asyncpg.Connection, player_id: int, a: dict[str, Any]) -> float:
    if "stat" in a:
        return float(await conn.fetchval("SELECT value FROM player_stats WHERE player_id = $1 AND stat = $2", player_id, a["stat"]) or 0)
    check = a["check"]
    if check == "vassals":
        return float(await conn.fetchval(
            "SELECT count(*) FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN villages v ON v.id = s.vassal_id WHERE o.player_id = $1 AND v.player_id <> $1",
            player_id))
    if check == "villages":
        return float(await conn.fetchval("SELECT count(*) FROM villages WHERE player_id = $1", player_id))
    if check in ("growth", "wonder"):
        village = game.content.pack["village"]
        b = (village.get("growth") or {}).get("building") if check == "growth" else ext(game, "wonder").get("building", "wonder")
        return float(await conn.fetchval(
            """SELECT coalesce(max((s->>'level')::int), 0) FROM villages v, jsonb_array_elements(v.state->'slots') s
               WHERE v.player_id = $1 AND s->>'building' = $2""", player_id, b))
    if check == "techs":
        return float(await conn.fetchval(
            "SELECT coalesce(max(jsonb_array_length(coalesce(state->'techs', '[]'))), 0) FROM villages WHERE player_id = $1", player_id))
    if check == "alliance":
        return float(bool(await conn.fetchval("SELECT 1 FROM alliance_members WHERE player_id = $1", player_id)))
    if check == "hero_level":
        from .heroes import level_of

        xp = await conn.fetchval("SELECT xp FROM heroes WHERE player_id = $1", player_id)
        return float(level_of(game, xp) if xp is not None else 0)
    return 0.0


async def check_achievements(game: Game, tx: Tx, player_id: int) -> list[str]:
    have = {r["id"] for r in await tx.conn.fetch("SELECT id FROM achievements WHERE player_id = $1", player_id)}
    new = []
    for a in ACHIEVEMENTS:
        if a["id"] not in have and await _measure(game, tx.conn, player_id, a) >= a["value"]:
            await tx.conn.execute("INSERT INTO achievements(player_id, id, at) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", player_id, a["id"], game.clock.now())
            game.event(tx, player_id, "achievement.unlocked", {"id": a["id"], "name": a["name"], "description": a["description"]})
            new.append(a["id"])
    return new


@router.get("/achievements")
async def achievements(player_id: PlayerId, game: GameDep) -> list[dict[str, Any]]:
    async with game.tx() as tx:
        await check_achievements(game, tx, player_id)
        got = {r["id"]: r["at"] for r in await tx.conn.fetch("SELECT id, at FROM achievements WHERE player_id = $1", player_id)}
        out = []
        for a in ACHIEVEMENTS:
            out.append({k: a[k] for k in ("id", "name", "description", "value")} | {
                "unlocked_at": got.get(a["id"]), "progress": min(a["value"], await _measure(game, tx.conn, player_id, a))})
        return out


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    await check_achievements(game, tx, attacker.player_id)


# -------------------------------------------------------------------- wonder


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    await check_achievements(game, tx, village.player_id)
    wb = ext(game, "wonder").get("building", "wonder")
    b = game.content.building(building)
    if building != wb or b is None or level < b["max_level"]:
        return
    if await tx.conn.fetchval("SELECT 1 FROM world_state WHERE key = 'winner'"):
        return
    name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", village.player_id)
    win = {"player": {"id": village.player_id, "name": name}, "village": village.public(), "at": game.clock.now()}
    await tx.conn.execute("INSERT INTO world_state(key, value) VALUES ('winner', $1)", win)
    tx.publish(game.topics.server, {"type": "world.won", "at": game.clock.now(), "data": win})


@router.get("/world/victory")
async def victory(game: GameDep) -> dict[str, Any]:
    """The winner, if any, and the cities furthest along with their wonder."""
    wb = ext(game, "wonder").get("building", "wonder")
    b = game.content.building(wb)
    async with game.pool.acquire() as conn:
        winner = await conn.fetchval("SELECT value FROM world_state WHERE key = 'winner'")
        race = await conn.fetch(
            """SELECT v.id, v.name, v.x, v.y, p.username, max((s->>'level')::int) AS level
               FROM villages v JOIN players p ON p.id = v.player_id, jsonb_array_elements(v.state->'slots') s
               WHERE s->>'building' = $1 AND (s->>'level')::int > 0 GROUP BY v.id, p.username ORDER BY level DESC LIMIT 10""", wb)
        return {"winner": winner, "building": wb, "max_level": b["max_level"] if b else None, "race": [dict(r) for r in race]}


module = Module("player_rules", router=router)
