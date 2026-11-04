"""Governors: named men and women who rule one city each.

- **Hiring.** Every player is offered ``candidates`` people of their own civilization, each with two
  ``traits``; the offer changes every ``refresh_hours`` (at world speed). Hiring costs ``hire`` ×
  (1 + governors already in service), paid by one of your cities. You may keep one governor per city
  you hold or rule (your own and your vassals').
- **Appointing.** A governor travels at ``speed`` tiles/hour from where they are (from your first
  city when at court) to an own city or a vassal's. In a vassal city the overlord's governor is a
  *prefect*: the city's own governor is sent back to its court, the people resent the foreign
  ruler (``prefect`` contentment) and the vassal cannot appoint anyone while the prefect rules.
- **Traits** (``traits``) change the city: ``contentment`` points; multipliers on unrest growth
  (``unrest``), calming (``calm``), crowding (``size``), tribute anger (``tribute``) and agitators
  (``agitators``); ``production`` (fraction, all resources) and ``defense`` (fraction).
- **Losing a city.** A vassal breaking free sends its prefect home; one that rises up kills them.

    extensions:
      governors: { hire: {...}, candidates: 3, refresh_hours: 24, speed: 8, prefect: -3, traits: {...}, names: { <tribe>: [...] } }
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_player, lock_villages, own_village, refresh_boost, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

ARRIVE = "governor.arrive"
router = APIRouter(tags=["governors"])
MULTIPLIERS = ("unrest", "calm", "size", "tribute", "agitators")


def cfg(game: Game) -> dict[str, Any] | None:
    return game.content.extensions.get("governors")


def _ms(game: Game, hours: float) -> int:
    return int(float(hours) * 3_600_000 / game.content.pack["world"]["speed"])


def trait(game: Game, tid: str) -> dict[str, Any]:
    return ((cfg(game) or {}).get("traits") or {}).get(tid) or {}


def ruler(v: VillageRow) -> dict[str, Any] | None:
    """The governor ruling a city (kept on the city as ``meta.governor``)."""
    return v.meta.get("governor")


def effects(game: Game, v: VillageRow) -> dict[str, Any]:
    """What the governor of ``v`` does: multipliers, contentment lines, production and defense."""
    out: dict[str, Any] = dict.fromkeys(MULTIPLIERS, 1.0) | {"points": [], "production": 0.0, "defense": 0.0}
    g = ruler(v)
    if not g or cfg(game) is None:
        return out
    for tid in g.get("traits", []):
        t = trait(game, tid)
        for k in MULTIPLIERS:
            out[k] *= float(t.get(k, 1.0))
        if t.get("contentment"):
            out["points"].append((f"Governor {g['name']}: {t.get('name', tid).lower()}", float(t["contentment"])))
        out["production"] += float(t.get("production", 0))
        out["defense"] += float(t.get("defense", 0))
    if g.get("prefect") and (cfg(game) or {}).get("prefect"):
        out["points"].append((f"A foreign prefect, {g['name']}", float(cfg(game)["prefect"])))
    return out


def view(game: Game, r: asyncpg.Record | dict[str, Any], places: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    places = places or {}
    return {"id": r["id"], "name": r["name"], "tribe": r["tribe"],
            "traits": [{"id": t, **{k: v for k, v in trait(game, t).items()}} for t in r["traits"]],
            "village": places.get(r["village_id"]) if r["village_id"] else None,
            "moving_to": places.get(r["moving_to"]) if r["moving_to"] else None,
            "arrives_at": r["arrives_at"], "hired_at": r["hired_at"]}


# -------------------------------------------------------------- candidates


def _candidates(game: Game, player: dict[str, Any], meta: dict[str, Any]) -> tuple[list[dict[str, Any]], int, bool]:
    """The people on offer and when the offer changes; ``True`` when a new offer was drawn."""
    c = cfg(game) or {}
    now = game.clock.now()
    offer = meta.get("governor_candidates") or {}
    if offer.get("until", 0) > now and offer.get("list") is not None:
        return offer["list"], offer["until"], False
    period = _ms(game, float(c.get("refresh_hours", 24)))
    until = (now // period + 1) * period
    rnd = random.Random(f"{game.settings.world_id}:{player['id']}:{until}")
    names = (c.get("names") or {}).get(player["tribe"]) or (c.get("names") or {}).get("default") or ["Anonymous"]
    traits = list((c.get("traits") or {}).keys())
    out = []
    for name in rnd.sample(names, min(len(names), int(c.get("candidates", 3)))):
        out.append({"name": name, "traits": rnd.sample(traits, min(2, len(traits)))})
    meta["governor_candidates"] = {"until": until, "list": out}
    return out, until, True


async def _limits(game: Game, conn: asyncpg.Connection, player_id: int) -> tuple[int, int, dict[str, float]]:
    """(governors in service, most allowed, cost of the next one)."""
    n = await conn.fetchval("SELECT count(*) FROM governors WHERE player_id = $1", player_id)
    held = await conn.fetchval("SELECT count(*) FROM villages WHERE player_id = $1", player_id)
    ruled = await conn.fetchval(
        "SELECT count(*) FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN villages v ON v.id = s.vassal_id "
        "WHERE o.player_id = $1 AND v.player_id <> $1", player_id)
    hire = (cfg(game) or {}).get("hire") or {}
    return int(n), int(held + ruled), {r: float(round(float(x) * (1 + n))) for r, x in hire.items()}


async def _places(conn: asyncpg.Connection, ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = await conn.fetch("SELECT id, name, x, y, player_id FROM villages WHERE id = ANY($1::bigint[])", [i for i in ids if i])
    return {r["id"]: dict(r) for r in rows}


@router.get("/me/governors")
async def mine(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Your governors, the people you could hire, and what the next one costs."""
    if cfg(game) is None:
        raise rule("no_governors", "this world has no governors")
    async with game.tx() as tx:
        player = await get_player(tx.conn, player_id, lock=True)
        meta = dict(player.get("meta") or {})
        cands, until, fresh = _candidates(game, player, meta)
        if fresh:
            await tx.conn.execute("UPDATE players SET meta = $2 WHERE id = $1", player_id, meta)
        rows = await tx.conn.fetch("SELECT * FROM governors WHERE player_id = $1 ORDER BY id", player_id)
        places = await _places(tx.conn, [i for r in rows for i in (r["village_id"], r["moving_to"])])
        n, most, cost = await _limits(game, tx.conn, player_id)
        traits = cfg(game).get("traits") or {}
        return {"governors": [view(game, r, places) for r in rows],
                "candidates": [{"index": i, "name": c["name"], "traits": [{"id": t, **traits.get(t, {})} for t in c["traits"]]}
                               for i, c in enumerate(cands)],
                "offer_until": until, "count": n, "max": most, "cost": cost, "speed": float(cfg(game).get("speed", 8))}


class Hire(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    candidate: int = Field(ge=0)
    #: The city that pays.
    from_: int = Field(alias="from")


@router.post("/me/governors", status_code=201)
async def hire(body: Hire, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Hire one of the candidates on offer; they wait at court until you appoint them."""
    if cfg(game) is None:
        raise rule("no_governors", "this world has no governors")
    from .villages import push_village, spend

    async with game.tx() as tx:
        player = await get_player(tx.conn, player_id, lock=True)
        meta = dict(player.get("meta") or {})
        cands, _, _ = _candidates(game, player, meta)
        if body.candidate >= len(cands):
            raise not_found("unknown_candidate")
        n, most, cost = await _limits(game, tx.conn, player_id)
        if n >= most:
            raise rule("too_many_governors", f"one governor per city you hold or rule ({most})")
        v = await own_village(tx.conn, body.from_, player_id, lock=True)
        await accrue(game, tx, v)
        if not all(v.state["resources"].get(r, 0) >= x for r, x in cost.items()):
            raise rule("insufficient_resources")
        spend(v, cost)
        pick = cands.pop(body.candidate)
        meta["governor_candidates"]["list"] = cands
        await tx.conn.execute("UPDATE players SET meta = $2 WHERE id = $1", player_id, meta)
        gid = await tx.conn.fetchval("INSERT INTO governors(player_id, name, tribe, traits, hired_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                                     player_id, pick["name"], player["tribe"], pick["traits"], game.clock.now())
        await save_village(game, tx, v)
        await push_village(game, tx, v)
    return {"id": gid, **(await mine(player_id, game))}


async def _rules_city(conn: asyncpg.Connection, player_id: int, v: VillageRow) -> str | None:
    """``own`` or ``vassal`` when ``player_id`` may appoint a governor in ``v``."""
    if v.player_id == player_id:
        return "own"
    lord = await conn.fetchval("SELECT o.player_id FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE s.vassal_id = $1", v.id)
    return "vassal" if lord == player_id else None


async def _leave(game: Game, tx: Tx, g: asyncpg.Record | dict[str, Any]) -> None:
    """``g`` stops ruling its city (if any)."""
    if not g["village_id"]:
        return
    v = (await lock_villages(tx.conn, g["village_id"])).get(g["village_id"])
    await tx.conn.execute("UPDATE governors SET village_id = NULL WHERE id = $1", g["id"])
    if v is not None and (ruler(v) or {}).get("id") == g["id"]:
        await refresh_boost(game, tx, v)  # settle at the old production first
        v.meta.pop("governor", None)
        await refresh_boost(game, tx, v)
        await save_village(game, tx, v)


class Appoint(BaseModel):
    village_id: int


@router.post("/governors/{governor_id}/appoint")
async def appoint(governor_id: int, body: Appoint, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Send a governor to rule one of your cities or a vassal's; they travel there first."""
    async with game.tx() as tx:
        g = await tx.conn.fetchrow("SELECT * FROM governors WHERE id = $1 AND player_id = $2 FOR UPDATE", governor_id, player_id)
        if g is None:
            raise not_found("governor_not_found")
        dest = (await lock_villages(tx.conn, body.village_id)).get(body.village_id)
        if dest is None:
            raise not_found("village_not_found")
        kind = await _rules_city(tx.conn, player_id, dest)
        if kind is None:
            raise rule("not_your_city", "governors rule your own cities and your vassals'")
        if g["village_id"] == dest.id:
            raise rule("same_village", "the governor already rules there")
        other = await tx.conn.fetchrow("SELECT id, player_id FROM governors WHERE (village_id = $1 OR moving_to = $1) AND id <> $2",
                                       dest.id, governor_id)
        if other is not None and other["player_id"] == player_id:
            raise rule("city_has_governor", "another of your governors rules or is going there")
        if kind == "own" and (ruler(dest) or {}).get("prefect"):
            raise rule("prefect_rules", "your overlord's prefect rules this city")
        src_id = g["village_id"] or g["moving_to"] or await tx.conn.fetchval("SELECT min(id) FROM villages WHERE player_id = $1", player_id)
        src = await tx.conn.fetchrow("SELECT x, y FROM villages WHERE id = $1", src_id) if src_id else None
        await _leave(game, tx, g)
        await tx.conn.execute("DELETE FROM jobs WHERE kind = $1 AND (payload->>'governor_id')::bigint = $2", ARRIVE, governor_id)
        d = math.hypot(src["x"] - dest.x, src["y"] - dest.y) if src else 0.0
        due = game.clock.now() + max(1000, _ms(game, d / max(0.1, float((cfg(game) or {}).get("speed", 8)))))
        await tx.conn.execute("UPDATE governors SET moving_to = $2, arrives_at = $3 WHERE id = $1", governor_id, dest.id, due)
        await game.schedule(tx, ARRIVE, due, {"governor_id": governor_id}, village_id=dest.id)
    return await mine(player_id, game)


@router.post("/governors/{governor_id}/recall")
async def recall(governor_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Call a governor back to court: the city is left without one."""
    async with game.tx() as tx:
        g = await tx.conn.fetchrow("SELECT * FROM governors WHERE id = $1 AND player_id = $2 FOR UPDATE", governor_id, player_id)
        if g is None:
            raise not_found("governor_not_found")
        await _leave(game, tx, g)
        await tx.conn.execute("DELETE FROM jobs WHERE kind = $1 AND (payload->>'governor_id')::bigint = $2", ARRIVE, governor_id)
        await tx.conn.execute("UPDATE governors SET moving_to = NULL, arrives_at = NULL WHERE id = $1", governor_id)
    return await mine(player_id, game)


@router.delete("/governors/{governor_id}")
async def dismiss(governor_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Let a governor go for good."""
    async with game.tx() as tx:
        g = await tx.conn.fetchrow("SELECT * FROM governors WHERE id = $1 AND player_id = $2 FOR UPDATE", governor_id, player_id)
        if g is None:
            raise not_found("governor_not_found")
        await _leave(game, tx, g)
        await tx.conn.execute("DELETE FROM jobs WHERE kind = $1 AND (payload->>'governor_id')::bigint = $2", ARRIVE, governor_id)
        await tx.conn.execute("DELETE FROM governors WHERE id = $1", governor_id)
    return await mine(player_id, game)


async def _install(game: Game, tx: Tx, g: asyncpg.Record, v: VillageRow, prefect: bool) -> None:
    await refresh_boost(game, tx, v)  # settle at the old production first
    await tx.conn.execute("UPDATE governors SET village_id = $2, moving_to = NULL, arrives_at = NULL WHERE id = $1", g["id"], v.id)
    v.meta["governor"] = {"id": g["id"], "name": g["name"], "tribe": g["tribe"], "traits": list(g["traits"]),
                          "player_id": g["player_id"], "prefect": prefect, "since": game.clock.now()}
    await refresh_boost(game, tx, v)
    await save_village(game, tx, v)


async def on_arrive(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    g = await tx.conn.fetchrow("SELECT * FROM governors WHERE id = $1 FOR UPDATE", job["payload"]["governor_id"])
    if g is None or g["moving_to"] is None:
        return
    v = (await lock_villages(tx.conn, g["moving_to"])).get(g["moving_to"])
    kind = await _rules_city(tx.conn, g["player_id"], v) if v else None
    if v is None or kind is None or (kind == "own" and (ruler(v) or {}).get("prefect")):
        await tx.conn.execute("UPDATE governors SET moving_to = NULL, arrives_at = NULL WHERE id = $1", g["id"])
        await add_report(game, tx, g["player_id"], "governor", f"Governor {g['name']} found no city to rule and came back to court", {})
        return
    old = await tx.conn.fetchrow("SELECT * FROM governors WHERE village_id = $1 FOR UPDATE", v.id)
    if old is not None:  # a prefect sends the city's own governor away
        await _leave(game, tx, old)
        v = (await lock_villages(tx.conn, v.id))[v.id]
        await add_report(game, tx, old["player_id"], "governor", f"Governor {old['name']} was sent away from {v.name} by a prefect",
                         {"village": v.public(), "prefect": g["name"]})
    await accrue(game, tx, v)
    await _install(game, tx, g, v, prefect=kind == "vassal")
    game.event(tx, g["player_id"], "governor.arrived", {"governor_id": g["id"], "village": v.public()})
    if kind == "vassal":
        await add_report(game, tx, v.player_id, "governor", f"{g['name']}, prefect of your overlord, now rules {v.name}",
                         {"village": v.public(), "governor": g["name"], "traits": list(g["traits"])})
    await push_village(game, tx, v)


# ------------------------------------------------------------------ hooks


@hookimpl
async def ovian_vassal_released(game: Game, tx: Tx, vassal: VillageRow, lord_id: int, lord_player_id: int | None, reason: str) -> None:
    """The prefect goes home, or, if the people rose up, dies at their hands."""
    g = ruler(vassal)
    if not g or not g.get("prefect"):
        return
    row = await tx.conn.fetchrow("SELECT * FROM governors WHERE id = $1 FOR UPDATE", g["id"])
    vassal.meta.pop("governor", None)
    await refresh_boost(game, tx, vassal)
    await save_village(game, tx, vassal)
    if row is None:
        return
    if reason in ("uprising", "rebellion"):
        await tx.conn.execute("DELETE FROM governors WHERE id = $1", row["id"])
        await add_report(game, tx, row["player_id"], "governor", f"Prefect {row['name']} was killed when {vassal.name} rose up",
                         {"village": vassal.public()})
        from .chronicle import record

        await record(game, tx, "prefect", f"The people of {vassal.name} killed the prefect {row['name']}", village=vassal)
    else:
        await tx.conn.execute("UPDATE governors SET village_id = NULL WHERE id = $1", row["id"])
        await add_report(game, tx, row["player_id"], "governor", f"Prefect {row['name']} left {vassal.name} and came back to court",
                         {"village": vassal.public()})


@hookimpl
async def ovian_production(game: Game, conn: asyncpg.Connection, village: VillageRow) -> dict[str, float]:
    p = effects(game, village)["production"]
    if not p:
        return {}
    return {r["id"]: p for r in game.content.pack["resources"]}


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    d = effects(game, defender)["defense"]
    if d:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
        battle.setdefault("modifiers", {})["governor_defense"] = d


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    if cfg(game) is None:
        return
    g = ruler(village)
    coming = await conn.fetchrow("SELECT g.id, g.name, g.traits, g.arrives_at, g.player_id FROM governors g WHERE g.moving_to = $1 "
                                 "ORDER BY arrives_at LIMIT 1", village.id)
    traits = cfg(game).get("traits") or {}
    view["governor"] = ({**g, "traits": [{"id": t, **traits.get(t, {})} for t in g.get("traits", [])]} if g else None)
    view["governor_coming"] = ({"id": coming["id"], "name": coming["name"], "arrives_at": coming["arrives_at"],
                                "prefect": coming["player_id"] != village.player_id,
                                "traits": [{"id": t, **traits.get(t, {})} for t in coming["traits"]]} if coming else None)


module = Module("governors", router=router, jobs={ARRIVE: on_arrive})
