"""Submission: cities beaten again and again become vassals.

When a player wins ``wins`` battles in a row against a city (a successful
defence resets the count), that city submits to the city that won the deciding
battle:

- **Tribute.** The vassal pays ``tribute`` (a fraction) of its gross production
  to its overlord, continuously. The engine applies it through the village
  state (``tribute`` on the vassal, ``tribute_in`` on the overlord); the repo
  keeps the two in step whenever the vassal's production changes.
- **Culture.** The vassal's culture now radiates for its overlord's player, and
  the city takes on the overlord's civilization (clients show its architecture).

- **Protection.** In return a vassal (not a colony, which is its owner's own city) gets
  ``benefits``: ``production`` (more of everything, a fraction), ``defense`` (a bonus in
  battles against anyone but its overlord), ``contentment`` (points of peace and order)
  and ``trade_speed`` (merchants and reinforcements between the vassal and its
  overlord's cities travel ``1 + trade_speed`` times faster).

**Voluntary vassalage.** A free city may offer fealty to another player's city
(``POST /villages/{id}/fealty`` with ``to``); that city's owner accepts or declines
(``POST /villages/{lord}/fealty/{vassal}/accept|decline``), and the offer can be withdrawn
(``DELETE /villages/{id}/fealty``). A voluntary vassal pays ``voluntary.tribute`` instead, gets the
same protection, and may renounce its oath at any time (``POST /villages/{id}/renounce``),
which counts as breaking free (its overlord's embassy falls to ruin).

**Taxes.** The overlord sets the tribute its vassals pay, between ``taxes.min`` and
``taxes.max``: a default for all of them (``POST /me/vassal-tax``) and, if it likes, a rate for
one city (``POST /villages/{lord}/vassals/{vassal}/tax``; ``rate: null`` follows the default
again). Taxes above the usual tribute (``tribute``, or ``voluntary.tribute``) anger the city:
``per_point`` contentment per percentage point, times ``1 + distance / taxes.distance`` (tiles to
the overlord's city), so far-off cities grow restless first. Lower taxes please it, wherever it lies.

A vassal breaks free by beating its overlord's city in battle, or when another
player beats it into submission. The overlord can also release it, except a
colony founded by a ver sacrum, which stays bound to its mother city.

Configured by the content pack::

    extensions:
      submission: { wins: 5, tribute: 0.1, kinds: [attack, raid],
                    benefits: { production: 0.05, defense: 0.15, contentment: 5, trade_speed: 0.5 },
                    voluntary: { tribute: 0.05 }, taxes: { min: 0, max: 0.3, per_point: 1, distance: 15 } }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, get_village, lock_villages, own_village, refresh_boost, refresh_tribute_in, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

router = APIRouter(tags=["submission"])


@dataclass
class Rules:
    wins: int
    tribute: float
    kinds: tuple[str, ...]
    benefits: dict[str, float]


BENEFITS = {"production": 0.05, "defense": 0.15, "contentment": 5.0, "trade_speed": 0.5}


def rules(game: Game) -> Rules:
    cfg = game.content.extensions.get("submission", {})
    benefits = {k: float((cfg.get("benefits") or {}).get(k, d)) if "benefits" not in cfg or k in (cfg["benefits"] or {}) else 0.0
                for k, d in BENEFITS.items()}
    return Rules(int(cfg.get("wins", 5)), float(cfg.get("tribute", 0.1)), tuple(cfg.get("kinds", ("attack", "raid"))), benefits)


def is_vassal(v: VillageRow) -> bool:
    """Pays tribute to an overlord and is not a colony of its own player (no database read)."""
    return bool(v.state.get("tribute")) and not v.meta.get("mother_id")


_PUB = "v.id, v.name, v.x, v.y, v.player_id, p.username AS player_name, p.tribe"


def _pub(r: asyncpg.Record) -> dict[str, Any]:
    return {"village": {"id": r["id"], "name": r["name"], "x": r["x"], "y": r["y"], "player_id": r["player_id"]},
            "player_name": r["player_name"], "tribe": r["tribe"]}


async def overlord_of(conn: asyncpg.Connection, village_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_PUB}, s.since, s.flow FROM vassals s JOIN villages v ON v.id = s.overlord_id JOIN players p ON p.id = v.player_id WHERE s.vassal_id = $1",
        village_id,
    )


TAXES = {"min": 0.0, "max": 0.3, "per_point": 1.0, "distance": 15.0}


def taxes(game: Game) -> dict[str, float]:
    c = (game.content.extensions.get("submission", {}) or {}).get("taxes") or {}
    return {k: float(c.get(k, d)) for k, d in TAXES.items()}


def usual_tribute(game: Game, v: VillageRow) -> float:
    return voluntary_tribute(game) if v.meta.get("voluntary") else rules(game).tribute


async def tax_rate(game: Game, conn: asyncpg.Connection, v: VillageRow) -> tuple[float, str]:
    """The tribute rate a vassal is taxed at, before foreign exchanges, and where it comes from (city, realm, usual)."""
    if v.meta.get("tax") is not None:
        return float(v.meta["tax"]), "city"
    lord_meta = await conn.fetchval(
        "SELECT p.meta FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN players p ON p.id = o.player_id WHERE s.vassal_id = $1", v.id)
    if lord_meta and lord_meta.get("vassal_tax") is not None:
        return float(lord_meta["vassal_tax"]), "realm"
    return usual_tribute(game, v), "usual"


async def apply_tax(game: Game, tx: Tx, v: VillageRow) -> None:
    """Re-apply a (locked) vassal's tax: its tribute, its overlord's income and its mood."""
    if not is_vassal(v):
        return
    from .contentment import enabled, settle
    from .embassies import tribute_factor

    await accrue(game, tx, v)
    rate, _ = await tax_rate(game, tx.conn, v)
    v.state["tribute"] = max(1e-6, rate * tribute_factor(game, v))  # never exactly 0: it is how a vassal is recognised
    await save_village(game, tx, v)
    lord = await tx.conn.fetchval("SELECT overlord_id FROM vassals WHERE vassal_id = $1", v.id)
    if lord:
        await refresh_tribute_in(game, tx, lord)
    if enabled(game):
        await settle(game, tx, v)


async def tax_mood(game: Game, conn: asyncpg.Connection, v: VillageRow) -> float:
    """Contentment from the tax: negative above the usual tribute (worse far from the overlord), positive below."""
    rate, _ = await tax_rate(game, conn, v)
    usual = usual_tribute(game, v)
    t = taxes(game)
    points = (rate - usual) * 100 * t["per_point"]
    if points <= 0:
        return round(-points, 1)
    pos = await conn.fetchrow("SELECT o.x, o.y FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE s.vassal_id = $1", v.id)
    d = ((pos["x"] - v.x) ** 2 + (pos["y"] - v.y) ** 2) ** 0.5 if pos else 0.0
    return round(-points * (1 + d / max(1.0, t["distance"])), 1)


def voluntary_tribute(game: Game) -> float:
    c = game.content.extensions.get("submission", {})
    return float((c.get("voluntary") or {}).get("tribute", rules(game).tribute / 2))


async def submit(game: Game, tx: Tx, vassal: VillageRow, lord: VillageRow, voluntary: bool = False) -> None:
    """Make ``vassal`` pay tribute to ``lord``, replacing any previous overlord."""
    if await tx.conn.fetchval("SELECT 1 FROM vassals WHERE vassal_id = $1", vassal.id):
        await release(game, tx, vassal, reason="conquered")
    await tx.conn.execute("DELETE FROM dominance WHERE target_id = $1", vassal.id)
    vassal.meta.pop("fealty_offer", None)
    if voluntary:
        vassal.meta["voluntary"] = True
    await bind(game, tx, vassal, lord, voluntary_tribute(game) if voluntary else rules(game).tribute)
    if lord.player_id != vassal.player_id:
        await apply_tax(game, tx, vassal)  # the overlord's own tax rate, if it set one
    if lord.player_id != vassal.player_id:
        await game.emit("ovian_vassal_bound", game=game, tx=tx, vassal=vassal, lord=lord)
    data = {"vassal": vassal.public(), "overlord": lord.public(), "tribute": vassal.state.get("tribute", 0), "voluntary": voluntary}
    game.event(tx, vassal.player_id, "village.submitted", data)
    game.event(tx, lord.player_id, "village.vassal_gained", data)
    from .chronicle import player_name, record

    how = "swore fealty" if voluntary else "bowed"
    await record(game, tx, "submission", f"{vassal.name} {how} to {await player_name(tx.conn, lord.player_id)} of {lord.name}",
                 village=vassal, player_id=lord.player_id, data={"overlord": lord.public(), "vassal": vassal.public()})


async def bind(game: Game, tx: Tx, vassal: VillageRow, lord: VillageRow, tribute: float) -> None:
    """Record ``vassal`` as paying ``tribute`` to ``lord`` (no checks, no events)."""
    await tx.conn.execute("INSERT INTO vassals(vassal_id, overlord_id, since) VALUES ($1, $2, $3)", vassal.id, lord.id, game.clock.now())
    await accrue(game, tx, vassal)  # settle at the old rate first
    from .contentment import unrest_now

    # unrest only gathers while a city pays tribute: settle it as a free city first,
    # or the hours since its last tick count against it and it may rise up at once
    vassal.meta["unrest"], vassal.meta["unrest_at"] = round(await unrest_now(game, tx.conn, vassal), 3), game.clock.now()
    from .embassies import tribute_factor

    vassal.state["tribute"] = tribute * tribute_factor(game, vassal)  # foreign exchanges lighten it
    await refresh_boost(game, tx, vassal)  # the overlord's protection
    await save_village(game, tx, vassal)  # sets the flow and the overlord's income


async def release(game: Game, tx: Tx, vassal: VillageRow, reason: str) -> None:
    lord_id = await tx.conn.fetchval("DELETE FROM vassals WHERE vassal_id = $1 RETURNING overlord_id", vassal.id)
    if lord_id is None:
        return
    await accrue(game, tx, vassal)
    vassal.state.pop("tribute", None)
    vassal.meta.pop("voluntary", None)
    vassal.meta.pop("tax", None)
    await refresh_boost(game, tx, vassal)
    await save_village(game, tx, vassal)
    lord = await refresh_tribute_in(game, tx, lord_id)
    await game.emit("ovian_vassal_released", game=game, tx=tx, vassal=vassal, lord_id=lord_id,
                    lord_player_id=lord.player_id if lord else None, reason=reason)
    data = {"vassal": vassal.public(), "overlord": lord.public() if lord else {"id": lord_id}, "reason": reason}
    game.event(tx, vassal.player_id, "village.freed", data)
    if lord:
        game.event(tx, lord.player_id, "village.vassal_lost", data)
    if reason in ("rebellion", "uprising"):
        from .chronicle import record

        how = "rose up and threw off" if reason == "uprising" else "rebelled against"
        await record(game, tx, "rebellion", f"{vassal.name} {how} {lord.name if lord else 'its overlord'}", village=vassal,
                     data={"overlord": data["overlord"], "reason": reason})


async def _reload(conn: asyncpg.Connection, *rows: VillageRow) -> None:
    """Refresh in-memory rows that this module may have changed through other objects."""
    for r in rows:
        fresh = await get_village(conn, r.id)
        r.state, r.population = fresh.state, fresh.population


# ------------------------------------------------------------------- battles


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    r = rules(game)
    if battle["kind"] not in r.kinds or attacker.player_id == defender.player_id or defender.meta.get("camp") or attacker.meta.get("camp"):
        return
    conn = tx.conn
    info: dict[str, Any] = {"needed": r.wins}
    if not result["attacker_won"]:
        await conn.execute("DELETE FROM dominance WHERE player_id = $1 AND target_id = $2", attacker.player_id, defender.id)
        report["submission"] = info | {"wins": 0, "reset": True}
        return

    mine = await overlord_of(conn, attacker.id)
    if mine and mine["id"] == defender.id:
        await release(game, tx, attacker, reason="rebellion")
        info["freed"] = True

    theirs = await overlord_of(conn, defender.id)
    if theirs and theirs["player_id"] == attacker.player_id:
        info["vassal"] = True  # already yours: nothing to count
    else:
        wins = await conn.fetchval(
            """INSERT INTO dominance(player_id, target_id, village_id, wins) VALUES ($1, $2, $3, 1)
               ON CONFLICT (player_id, target_id) DO UPDATE SET wins = dominance.wins + 1, village_id = EXCLUDED.village_id
               RETURNING wins""",
            attacker.player_id, defender.id, attacker.id,
        )
        info["wins"] = wins
        if wins >= r.wins:
            await submit(game, tx, defender, attacker)
            info["submitted"] = True
            info["tribute"] = r.tribute
    report["submission"] = info
    await _reload(conn, attacker, defender)


# ----------------------------------------------------------------- protection


@hookimpl
async def ovian_boost(game: Game, conn: asyncpg.Connection, village: VillageRow) -> float:
    return rules(game).benefits["production"] if is_vassal(village) else 0.0


@hookimpl
async def ovian_contentment(game: Game, conn: asyncpg.Connection, village: VillageRow) -> list[tuple[str, float]]:
    if not is_vassal(village):
        return []
    n = rules(game).benefits["contentment"]
    out = [("Peace under an overlord", n)] if n else []
    mood = await tax_mood(game, conn, village)
    if mood:
        out.append(("Heavy taxes" if mood < 0 else "Light taxes", mood))
    return out


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    d = rules(game).benefits["defense"]
    if not d or not is_vassal(defender):
        return
    lord = await overlord_of(tx.conn, defender.id)
    if lord is None or lord["player_id"] == attacker.player_id:
        return  # no protection against the overlord itself
    battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
    battle.setdefault("modifiers", {})["overlord_protection"] = d


@hookimpl
async def ovian_travel(game: Game, conn: asyncpg.Connection, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
    fast = rules(game).benefits["trade_speed"]
    if not fast or kind not in ("trade", "reinforce") or not (is_vassal(origin) or is_vassal(target)):
        return 1.0
    linked = await conn.fetchval(
        """SELECT 1 FROM vassals s JOIN villages o ON o.id = s.overlord_id
           WHERE (s.vassal_id = $1 AND o.player_id = $4) OR (s.vassal_id = $2 AND o.player_id = $3)""",
        origin.id, target.id, origin.player_id, target.player_id)
    return 1.0 / (1.0 + fast) if linked else 1.0


# --------------------------------------------------------------------- views


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    lord = await overlord_of(conn, village.id)
    view["submission"] = lord and _pub(lord) | {"since": lord["since"], "flow": lord["flow"], "tribute": village.state.get("tribute", 0),
                                                 "benefits": {k: n for k, n in rules(game).benefits.items() if n} if is_vassal(village) else {}}
    vassals = await conn.fetch(
        f"""SELECT {_PUB}, s.since, s.flow, (v.meta->>'mother_id')::bigint = s.overlord_id AS colony
            FROM vassals s JOIN villages v ON v.id = s.vassal_id JOIN players p ON p.id = v.player_id
            WHERE s.overlord_id = $1 ORDER BY s.since""",
        village.id,
    )
    view["vassals"] = [_pub(r) | {"since": r["since"], "flow": r["flow"], "colony": bool(r["colony"])} for r in vassals]
    t = taxes(game)
    pmeta = await conn.fetchval("SELECT meta FROM players WHERE id = $1", village.player_id) or {}
    view["taxes"] = {"min": t["min"], "max": t["max"], "usual": rules(game).tribute, "voluntary": voluntary_tribute(game),
                     "default": pmeta.get("vassal_tax")}
    for x in view["vassals"]:
        if x["colony"]:
            continue
        vv = await get_village(conn, x["village"]["id"])
        rate, source = await tax_rate(game, conn, vv)
        x["tax"] = {"rate": rate, "source": source, "usual": usual_tribute(game, vv), "mood": await tax_mood(game, conn, vv)}
    if view["submission"]:
        view["submission"]["colony"] = village.meta.get("mother_id") == lord["id"]
        view["submission"]["voluntary"] = bool(village.meta.get("voluntary"))
        if is_vassal(village):
            rate, source = await tax_rate(game, conn, village)
            view["submission"]["tax"] = {"rate": rate, "source": source, "usual": usual_tribute(game, village)}
    offer = village.meta.get("fealty_offer")
    if offer:
        to = await conn.fetchrow(f"SELECT {_PUB} FROM villages v JOIN players p ON p.id = v.player_id WHERE v.id = $1", offer["to"])
        view["fealty_offer"] = to and _pub(to) | {"at": offer["at"], "tribute": voluntary_tribute(game)}
    offers = await conn.fetch(
        f"""SELECT {_PUB}, (v.meta->'fealty_offer'->>'at')::bigint AS at FROM villages v JOIN players p ON p.id = v.player_id
            WHERE (v.meta->'fealty_offer'->>'to')::bigint = $1 ORDER BY v.id""", village.id)
    view["fealty_offers"] = [_pub(r) | {"at": r["at"], "tribute": voluntary_tribute(game)} for r in offers]
    # who is beating this city, and which cities this one is beating
    threats = await conn.fetch(
        "SELECT d.wins, p.id, p.username FROM dominance d JOIN players p ON p.id = d.player_id WHERE d.target_id = $1 ORDER BY d.wins DESC",
        village.id,
    )
    conquests = await conn.fetch(
        f"SELECT {_PUB}, d.wins FROM dominance d JOIN villages v ON v.id = d.target_id JOIN players p ON p.id = v.player_id WHERE d.village_id = $1 ORDER BY d.wins DESC",
        village.id,
    )
    view["dominance"] = {
        "needed": rules(game).wins,
        "threats": [{"player_id": t["id"], "player_name": t["username"], "wins": t["wins"]} for t in threats],
        "conquests": [_pub(c) | {"wins": c["wins"]} for c in conquests],
    }


# -------------------------------------------------------------------- orders


@router.post("/villages/{village_id}/vassals/{vassal_id}/release")
async def release_vassal(village_id: int, vassal_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Free a vassal city: it stops paying tribute."""
    from .villages import push_village

    async with game.tx() as tx:
        await own_village(tx.conn, village_id, player_id)
        if await tx.conn.fetchval("SELECT overlord_id FROM vassals WHERE vassal_id = $1", vassal_id) != village_id:
            raise not_found("vassal_not_found")
        vs = await lock_villages(tx.conn, village_id, vassal_id)
        if vs[vassal_id].meta.get("mother_id") == village_id:
            raise rule("colony_bound", "a colony founded by a ver sacrum stays bound to its mother city")
        await release(game, tx, vs[vassal_id], reason="released")
        await push_village(game, tx, vs[vassal_id])
        return await push_village(game, tx, await get_village(tx.conn, village_id))


class TaxOrder(BaseModel):
    #: Fraction of production; null follows the realm default again.
    rate: float | None


def _check_rate(game: Game, rate: float | None) -> float | None:
    if rate is None:
        return None
    t = taxes(game)
    if not t["min"] - 1e-9 <= rate <= t["max"] + 1e-9:
        raise rule("tax_out_of_range", f"taxes go from {t['min']:.0%} to {t['max']:.0%}")
    return round(rate, 4)


@router.post("/villages/{village_id}/vassals/{vassal_id}/tax")
async def tax_vassal(village_id: int, vassal_id: int, body: TaxOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Set the tribute rate of one vassal city (``rate: null``: follow the realm default)."""
    from .villages import push_village

    rate = _check_rate(game, body.rate)
    async with game.tx() as tx:
        await own_village(tx.conn, village_id, player_id)
        if await tx.conn.fetchval("SELECT overlord_id FROM vassals WHERE vassal_id = $1", vassal_id) != village_id:
            raise not_found("vassal_not_found")
        v = await get_village(tx.conn, vassal_id, lock=True)
        if not is_vassal(v):
            raise rule("colony_bound", "a colony pays its mother city a fixed tribute")
        if rate is None:
            v.meta.pop("tax", None)
        else:
            v.meta["tax"] = rate
        await apply_tax(game, tx, v)
        game.event(tx, v.player_id, "village.taxed", {"village_id": v.id, "rate": (await tax_rate(game, tx.conn, v))[0]})
        await push_village(game, tx, await get_village(tx.conn, vassal_id))
        return await push_village(game, tx, await get_village(tx.conn, village_id))


@router.post("/me/vassal-tax")
async def tax_realm(body: TaxOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Set the default tribute rate of all your vassals (``rate: null``: the usual tribute). Cities with their own rate keep it."""
    from .villages import push_village

    rate = _check_rate(game, body.rate)
    async with game.tx() as tx:
        meta = await tx.conn.fetchval("SELECT meta FROM players WHERE id = $1 FOR UPDATE", player_id) or {}
        if rate is None:
            meta.pop("vassal_tax", None)
        else:
            meta["vassal_tax"] = rate
        await tx.conn.execute("UPDATE players SET meta = $2 WHERE id = $1", player_id, meta)
        ids = await tx.conn.fetch(
            """SELECT s.vassal_id FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN villages v ON v.id = s.vassal_id
               WHERE o.player_id = $1 AND v.player_id <> $1 ORDER BY s.vassal_id""", player_id)
        for r in ids:
            v = await get_village(tx.conn, r["vassal_id"], lock=True)
            await apply_tax(game, tx, v)
            await push_village(game, tx, await get_village(tx.conn, v.id))
        return {"default": rate, "vassals": len(ids)}


class FealtyOffer(BaseModel):
    #: The city to swear fealty to.
    to: int


@router.post("/villages/{village_id}/fealty")
async def offer_fealty(village_id: int, body: FealtyOffer, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Offer this free city as a vassal of another player's city; its owner may accept."""
    from .villages import push_village

    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        lord = await get_village(tx.conn, body.to)
        if lord.player_id == player_id:
            raise rule("own_city", "you cannot swear fealty to your own city")
        if await tx.conn.fetchval("SELECT npc FROM players WHERE id = $1", lord.player_id):
            raise rule("npc_city", "nobody there to accept your oath")
        if await tx.conn.fetchval("SELECT 1 FROM vassals WHERE vassal_id = $1", v.id):
            raise rule("already_vassal", "this city already pays tribute; break free first")
        v.meta["fealty_offer"] = {"to": lord.id, "at": game.clock.now()}
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        data = {"vassal": v.public(), "overlord": lord.public(), "tribute": voluntary_tribute(game)}
        game.event(tx, lord.player_id, "village.fealty_offered", data)
        from ..repo import add_report

        await add_report(game, tx, lord.player_id, "fealty", f"{v.name} offers to become a vassal of {lord.name}", data)
        return await push_village(game, tx, v)


@router.delete("/villages/{village_id}/fealty")
async def withdraw_fealty(village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        v.meta.pop("fealty_offer", None)
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        return await push_village(game, tx, v)


@router.post("/villages/{village_id}/fealty/{vassal_id}/{answer}")
async def answer_fealty(village_id: int, vassal_id: int, answer: str, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Accept or decline a city's offer of fealty to this city."""
    from .villages import push_village

    if answer not in ("accept", "decline"):
        raise not_found("not_found")
    async with game.tx() as tx:
        await own_village(tx.conn, village_id, player_id)
        vs = await lock_villages(tx.conn, village_id, vassal_id)
        lord, vassal = vs.get(village_id), vs.get(vassal_id)
        if vassal is None or (vassal.meta.get("fealty_offer") or {}).get("to") != village_id:
            raise not_found("offer_not_found")
        data = {"vassal": vassal.public(), "overlord": lord.public()}
        if answer == "decline" or await tx.conn.fetchval("SELECT 1 FROM vassals WHERE vassal_id = $1", vassal.id):
            vassal.meta.pop("fealty_offer", None)
            await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", vassal.id, vassal.meta)
            game.event(tx, vassal.player_id, "village.fealty_declined", data)
            if answer == "accept":
                raise rule("already_vassal", "that city now pays tribute to someone else")
        else:
            await accrue(game, tx, vassal)
            await submit(game, tx, vassal, lord, voluntary=True)
        await push_village(game, tx, vassal)
        return await push_village(game, tx, await get_village(tx.conn, village_id))


@router.post("/villages/{village_id}/renounce")
async def renounce(village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """A voluntary vassal takes back its oath: it stops paying tribute."""
    from .villages import push_village

    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        if not v.meta.get("voluntary") or not await tx.conn.fetchval("SELECT 1 FROM vassals WHERE vassal_id = $1", v.id):
            raise rule("not_voluntary", "only a vassal that swore fealty of its own will can renounce it")
        await release(game, tx, v, reason="renounced")
        return await push_village(game, tx, v)


module = Module("submission", router=router)
