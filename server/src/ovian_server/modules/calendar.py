"""The world calendar: seasons, and a festival once a year.

**Seasons** (``extensions.seasons``) follow each other every ``hours`` (at world
speed) from the moment the world started. Each may change production per resource
(``production``, ``all`` for every one), travel time (``travel``, 1.25 = slower) and
contentment (``contentment`` points)::

    seasons:
      hours: 24
      list:
        - { id: spring, name: Spring, production: { food: 0.1 }, contentment: 5 }
        - { id: winter, name: Winter, production: { food: -0.25 }, travel: 1.25 }

**The festival** (``extensions.festival``) is held during one season each year.
Every player may enter each contest once, from one city:

- ``kind: resources``: offer goods (they are spent); the most generous wins. Entries add up.
- ``kind: army``: the attack strength of the troops at home in that city.
- ``kind: culture``: the player's total culture.

When the season ends, the best ``len(prizes)`` of each contest get the prizes:
resources delivered to the city they entered from, favor, a contentment glow in
all their cities, and a medal (category ``games_<contest>``).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, own_village, refresh_all, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

TURN = "season.turn"
router = APIRouter(tags=["calendar"])


def seasons(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("seasons", {})


def festival_cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("festival", {})


def season_ms(game: Game) -> int:
    return int(float(seasons(game).get("hours", 24)) * 3_600_000 / game.content.pack["world"]["speed"])


def _epoch(game: Game) -> int:
    return int(game.__dict__.get("_calendar_epoch", 0))


async def load_epoch(game: Game, conn: asyncpg.Connection) -> int:
    e = await conn.fetchval("SELECT (value #>> '{}')::bigint FROM world_state WHERE key = 'calendar_epoch'")
    if e is None:
        e = game.clock.now()
        await conn.execute("INSERT INTO world_state(key, value) VALUES ('calendar_epoch', to_jsonb($1::bigint)) ON CONFLICT (key) DO NOTHING", e)
        e = await conn.fetchval("SELECT (value #>> '{}')::bigint FROM world_state WHERE key = 'calendar_epoch'")
    game.__dict__["_calendar_epoch"] = int(e)
    return int(e)


def when(game: Game, at: int | None = None) -> dict[str, Any]:
    """Season index, year and bounds at ``at`` (default now)."""
    lst = seasons(game).get("list", [])
    if not lst:
        return {}
    at = game.clock.now() if at is None else at
    n = max(0, at - _epoch(game)) // season_ms(game)
    i = int(n % len(lst))
    start = _epoch(game) + n * season_ms(game)
    return {"index": i, "year": int(n // len(lst)) + 1, "started_at": start, "ends_at": start + season_ms(game), **lst[i]}


def festival_now(game: Game, at: int | None = None) -> dict[str, Any] | None:
    """The festival being held now, if any: its number (the year), opening and closing."""
    f = festival_cfg(game)
    w = when(game, at)
    if not f or not w or w.get("id") != f.get("season"):
        return None
    return {"number": w["year"], "opens_at": w["started_at"], "closes_at": w["ends_at"]}


def _resources(game: Game, spec: dict[str, Any]) -> dict[str, float]:
    ids = [r["id"] for r in game.content.pack["resources"]]
    out: dict[str, float] = {}
    for k, n in (spec or {}).items():
        for r in ids if k == "all" else [k]:
            if r in ids:
                out[r] = out.get(r, 0.0) + float(n)
    return out


# ------------------------------------------------------------------- endpoints


@router.get("/calendar")
async def calendar(game: GameDep, player_id: PlayerId) -> dict[str, Any]:
    """The season, the year, and the festival with its standings."""
    w = when(game)
    f = festival_cfg(game)
    out: dict[str, Any] = {"season": w or None, "seasons": seasons(game).get("list", []), "season_ms": season_ms(game) if w else None}
    if not f:
        return out
    now = festival_now(game)
    lst = seasons(game).get("list", [])
    nxt = None
    if not now and w:
        idx = next((i for i, s in enumerate(lst) if s.get("id") == f.get("season")), 0)
        ahead = (idx - w["index"]) % len(lst)
        nxt = w["started_at"] + ahead * season_ms(game)
    number = now["number"] if now else None
    async with game.pool.acquire() as conn:
        contests = {}
        for cid, c in f.get("contests", {}).items():
            rows = await conn.fetch(
                """SELECT e.player_id, p.username, e.score FROM festival_entries e JOIN players p ON p.id = e.player_id
                   WHERE e.festival = $1 AND e.contest = $2 ORDER BY e.score DESC LIMIT 10""", number or 0, cid)
            mine = await conn.fetchval("SELECT score FROM festival_entries WHERE festival = $1 AND contest = $2 AND player_id = $3",
                                       number or 0, cid, player_id)
            contests[cid] = c | {"standings": [dict(r) for r in rows], "mine": mine}
        last = await conn.fetchval("SELECT value FROM world_state WHERE key = 'festival_results'")
    out["festival"] = {"name": f.get("name", "Festival"), "text": f.get("text", ""), "season": f.get("season"), "active": bool(now),
                       "number": number, "opens_at": now["opens_at"] if now else nxt, "closes_at": now["closes_at"] if now else None,
                       "prizes": f.get("prizes", []), "contests": contests, "last": last}
    return out


class Entry(BaseModel):
    village_id: int
    resources: dict[str, float] = Field(default_factory=dict)


@router.post("/festival/{contest}")
async def enter(contest: str, body: Entry, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Enter a contest of the festival being held."""
    from .villages import push_village

    f = festival_cfg(game)
    c = f.get("contests", {}).get(contest)
    if c is None:
        raise not_found("unknown_contest")
    now = festival_now(game)
    if not now:
        raise rule("no_festival", "the festival is not being held now")
    async with game.tx() as tx:
        v = await own_village(tx.conn, body.village_id, player_id, lock=True)
        kind = c.get("kind", "resources")
        if kind == "resources":
            allowed = set(c.get("resources") or [r["id"] for r in game.content.pack["resources"]])
            offer = {k: math.floor(float(n)) for k, n in body.resources.items() if n and k in allowed}
            if not offer or any(n < 0 for n in offer.values()):
                raise rule("nothing_offered", "offer some " + ", ".join(sorted(allowed)))
            await accrue(game, tx, v)
            if any(v.state["resources"].get(k, 0) < n for k, n in offer.items()):
                raise rule("insufficient_resources")
            for k, n in offer.items():
                v.state["resources"][k] -= n
            await save_village(game, tx, v)
            score = float(sum(offer.values()))
            sql = "score = festival_entries.score + EXCLUDED.score"
        elif kind == "army":
            units = {u["id"]: u for u in game.content.pack["units"]}
            score = float(sum(units[k]["attack"] * n for k, n in v.state.get("units", {}).items() if k in units))
            if score <= 0:
                raise rule("no_units", "you need troops at home in this city")
            sql = "score = greatest(festival_entries.score, EXCLUDED.score)"
        else:
            score = float(await tx.conn.fetchval("SELECT coalesce(sum(culture), 0) FROM villages WHERE player_id = $1", player_id))
            if score <= 0:
                raise rule("no_culture", "your cities have no culture yet")
            sql = "score = greatest(festival_entries.score, EXCLUDED.score)"
        await tx.conn.execute(
            f"""INSERT INTO festival_entries(festival, contest, player_id, village_id, score, at) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (festival, contest, player_id) DO UPDATE SET {sql}, village_id = EXCLUDED.village_id, at = EXCLUDED.at""",
            now["number"], contest, player_id, v.id, score, game.clock.now())
        await push_village(game, tx, v)
    return await calendar(game, player_id)


# ---------------------------------------------------------------- the year turns


async def award(game: Game, tx: Tx, number: int) -> dict[str, Any]:
    from .contentment import add_effect, schedule_end
    from .chronicle import record
    from .villages import push_village

    f = festival_cfg(game)
    prizes = f.get("prizes", [])
    results: dict[str, Any] = {"number": number, "name": f.get("name", "Festival"), "contests": {}}
    for cid, c in f.get("contests", {}).items():
        rows = await tx.conn.fetch(
            """SELECT e.player_id, e.village_id, e.score, p.username FROM festival_entries e JOIN players p ON p.id = e.player_id
               WHERE e.festival = $1 AND e.contest = $2 ORDER BY e.score DESC, e.at LIMIT $3""", number, cid, len(prizes))
        winners = []
        for rank, (r, prize) in enumerate(zip(rows, prizes), start=1):
            winners.append({"rank": rank, "player": {"id": r["player_id"], "name": r["username"]}, "score": r["score"]})
            vid = r["village_id"] or await tx.conn.fetchval("SELECT min(id) FROM villages WHERE player_id = $1", r["player_id"])
            from ..repo import get_village

            try:
                v = await get_village(tx.conn, vid, lock=True)
            except Exception:  # noqa: BLE001 - the city is gone
                continue
            await accrue(game, tx, v)
            for k, n in _resources(game, prize.get("resources", {})).items():
                v.state["resources"][k] = v.state["resources"].get(k, 0) + n
            if prize.get("favor"):
                from . import gods

                gods.settle(game, v)
                v.meta["favor"] = min(float(gods.cfg(game).get("max_favor", 500)), v.meta["favor"] + float(prize["favor"]))
            await save_village(game, tx, v)
            if prize.get("contentment"):
                pmeta = await tx.conn.fetchval("SELECT meta FROM players WHERE id = $1 FOR UPDATE", r["player_id"])
                until = add_effect(game, pmeta, "contentment", f"Glory at the {f.get('name', 'festival')}", float(prize["contentment"]),
                                   float(prize.get("hours", seasons(game).get("hours", 24))))
                await tx.conn.execute("UPDATE players SET meta = $2 WHERE id = $1", r["player_id"], pmeta)
                await schedule_end(game, tx, until, player_id=r["player_id"])
            await tx.conn.execute(
                "INSERT INTO medals(player_id, round, period, category, rank, value, at) VALUES ($1, (SELECT coalesce((SELECT (value #>> '{}')::int FROM world_state WHERE key = 'round'), 1)), $2, $3, $4, $5, $6)",
                r["player_id"], number, f"games_{cid}", rank, r["score"], game.clock.now())
            await add_report(game, tx, r["player_id"], "festival", f"{['First', 'Second', 'Third'][min(rank, 3) - 1] if rank <= 3 else f'#{rank}'} in the {c.get('name', cid)}",
                             {"contest": cid, "rank": rank, "score": r["score"], "prize": prize, "festival": f.get("name")})
            await push_village(game, tx, v)
            if rank == 1:
                await record(game, tx, "festival", f"{r['username']} won the {c.get('name', cid)} at the {f.get('name', 'festival')} of year {number}",
                             village=v, player_id=r["player_id"], data={"contest": cid, "score": r["score"]})
        results["contests"][cid] = {"name": c.get("name", cid), "winners": winners}
    await tx.conn.execute("INSERT INTO world_state(key, value) VALUES ('festival_results', $1) ON CONFLICT (key) DO UPDATE SET value = $1", results)
    tx.publish(game.topics.server, {"type": "festival.ended", "at": game.clock.now(), "data": results})
    return results


async def on_turn(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await load_epoch(game, tx.conn)
    now = game.clock.now()
    prev = job["payload"].get("festival")
    if prev and not festival_now(game, now):
        await award(game, tx, int(prev))
    w = when(game, now)
    if not w:
        return
    await refresh_all(game, tx=tx)
    tx.publish(game.topics.server, {"type": "season.changed", "at": now, "data": w})
    fest = festival_now(game, now)
    if fest and job["payload"].get("index") != w["index"]:
        tx.publish(game.topics.server, {"type": "festival.opened", "at": now, "data": fest | {"name": festival_cfg(game).get("name")}})
    await game.schedule(tx, TURN, w["ends_at"], {"index": (w["index"] + 1) % len(seasons(game)["list"]),
                                                 "festival": fest["number"] if fest else None})


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.tx() as tx:
        await load_epoch(game, tx.conn)
        if not seasons(game).get("list"):
            return
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", TURN):
            w = when(game)
            fest = festival_now(game)
            await game.schedule(tx, TURN, w["ends_at"], {"index": w["index"], "festival": fest["number"] if fest else None})


@hookimpl
async def ovian_production(game: Game, conn: asyncpg.Connection, village: VillageRow) -> dict[str, float]:
    w = when(game)
    return _resources(game, w.get("production", {})) if w else {}


@hookimpl
async def ovian_contentment(game: Game, conn: asyncpg.Connection, village: VillageRow) -> list[tuple[str, float]]:
    w = when(game)
    return [(w["name"], float(w["contentment"]))] if w and w.get("contentment") else []


@hookimpl
async def ovian_travel(game: Game, conn: asyncpg.Connection, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
    w = when(game, at)
    return float(w.get("travel", 1.0)) if w else 1.0


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    w = when(game)
    if w:
        view["season"] = {k: w[k] for k in ("id", "name", "year", "index", "started_at", "ends_at")}
        fest = festival_now(game)
        if fest:
            view["season"]["festival"] = fest | {"name": festival_cfg(game).get("name")}


module = Module("calendar", router=router, jobs={TURN: on_turn})
