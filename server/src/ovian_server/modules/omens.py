"""Omens: now and then something happens in a city, and its ruler must choose.

Every ``every_hours`` (at world speed) each active city has a ``chance`` of an omen,
if it has none pending. It waits ``expire_hours`` for an answer; then the
``default`` choice happens by itself. ``POST /villages/{id}/omen/{choice}`` answers.

Events live in ``extensions.omens.events`` (the built-in set below is used when a
pack lists none). A choice may cost resources (``cost``, in hours of the city's
production, so it scales with the city) or favor (``favor_cost``), and has effects:

- ``gain``: resources, in hours of production (negative to lose some);
- ``favor``: favor points;
- ``contentment`` + ``hours``: a timed mood;
- ``boost`` + ``hours``: a timed production bonus (negative for a malus);
- ``unrest``: added unrest (vassals only).

Resource keys may be a resource id, ``all`` or ``upkeep`` (the resource that feeds troops).
An event may require a building (``requires: { temple: 1 }``) or a season (``seasons: [winter]``).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_village, hosted_upkeep, own_village, refresh_boost, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

TICK = "omens.tick"
EXPIRE = "omen.expire"
router = APIRouter(tags=["omens"])

EVENTS: list[dict[str, Any]] = [
    {"id": "plague", "title": "Sickness in the lower town", "text": "A fever spreads through the crowded streets near the river.",
     "default": "endure", "choices": [
        {"id": "physicians", "label": "Send for physicians", "cost": {"upkeep": 2, "all": 0.5}, "contentment": 5, "hours": 12},
        {"id": "pray", "label": "Pray at the temple", "favor_cost": 30, "requires": {"temple": 1}, "contentment": 2, "hours": 12},
        {"id": "endure", "label": "Let it run its course", "contentment": -15, "boost": -0.1, "hours": 12}]},
    {"id": "harvest", "title": "A bumper harvest", "text": "The fields gave more than the granaries can hold.", "default": "store",
     "choices": [
        {"id": "store", "label": "Fill the granaries", "gain": {"upkeep": 4}},
        {"id": "feast", "label": "Hold a feast for all", "gain": {"upkeep": 1}, "contentment": 15, "hours": 24}]},
    {"id": "prophet", "title": "A prophet in the agora", "text": "A wild-eyed seer foretells greatness, and doom, to anyone who listens.",
     "default": "ignore", "choices": [
        {"id": "welcome", "label": "Welcome the prophet", "favor": 40, "contentment": -5, "hours": 6},
        {"id": "banish", "label": "Banish the prophet", "contentment": 5, "hours": 6},
        {"id": "ignore", "label": "Let them talk"}]},
    {"id": "caravan", "title": "A lost caravan", "text": "Foreign merchants, lost and hungry, ask for shelter at the gates.", "default": "shelter",
     "choices": [
        {"id": "shelter", "label": "Shelter them", "cost": {"upkeep": 1}, "gain": {"all": 1.5}},
        {"id": "rob", "label": "Seize their goods", "gain": {"all": 4}, "contentment": -10, "hours": 24}]},
    {"id": "eclipse", "title": "The sun goes dark", "text": "At midday the sun vanished. The people are afraid.", "default": "ignore",
     "choices": [
        {"id": "sacrifice", "label": "Offer a great sacrifice", "cost": {"upkeep": 3}, "favor": 30, "contentment": 5, "hours": 12},
        {"id": "ignore", "label": "Explain it away", "contentment": -10, "hours": 12}]},
    {"id": "artist", "title": "A famous sculptor", "text": "A renowned sculptor offers to adorn the city, for a price.", "default": "decline",
     "choices": [
        {"id": "commission", "label": "Commission a statue", "cost": {"all": 3}, "contentment": 10, "hours": 48, "artwork": "statue"},
        {"id": "decline", "label": "Decline politely"}]},
    {"id": "fire", "title": "Fire in the timber yard", "text": "Flames leap from the stacks of timber by the walls.", "default": "burn",
     "choices": [
        {"id": "fight", "label": "Everyone to the buckets", "boost": -0.15, "hours": 3},
        {"id": "burn", "label": "Save what you can", "gain": {"wood": -6}, "contentment": -5, "hours": 6}]},
    {"id": "boom", "title": "Markets overflow", "text": "Traders from afar crowd the market square.", "default": "tax",
     "requires": {"market": 1}, "choices": [
        {"id": "tax", "label": "Tax them", "gain": {"all": 2}},
        {"id": "welcome", "label": "Let trade flow freely", "boost": 0.15, "hours": 12}]},
    {"id": "frost", "title": "A bitter frost", "text": "Ice cracks the cisterns and the herds huddle together.", "default": "endure",
     "seasons": ["winter"], "choices": [
        {"id": "firewood", "label": "Burn firewood for all", "cost": {"wood": 3}, "contentment": 5, "hours": 12},
        {"id": "endure", "label": "Endure", "boost": -0.1, "hours": 12, "contentment": -5}]},
    {"id": "games", "title": "Youths at the games", "text": "The young men want games of their own, like those at the great festival.",
     "default": "no", "seasons": ["summer"], "choices": [
        {"id": "yes", "label": "Hold games", "cost": {"all": 1}, "contentment": 12, "hours": 24},
        {"id": "no", "label": "There is work to do", "contentment": -3, "hours": 12}]},
]


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("omens", {})


def events(game: Game) -> list[dict[str, Any]]:
    return cfg(game).get("events") or EVENTS


def _ms(game: Game, hours: float) -> int:
    return int(hours * 3_600_000 / game.content.pack["world"]["speed"])


def _levels(v: VillageRow) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in v.state["slots"]:
        if s.get("building"):
            out[s["building"]] = max(out.get(s["building"], 0), s["level"])
    return out


def _ok(req: dict[str, int] | None, levels: dict[str, int]) -> bool:
    return all(levels.get(b, 0) >= n for b, n in (req or {}).items())


def _hours_of(game: Game, eco: dict[str, Any], spec: dict[str, float]) -> dict[str, float]:
    """Resources worth ``spec`` hours of this city's gross production."""
    ids = [r["id"] for r in game.content.pack["resources"]]
    from .contentment import upkeep_resource

    upkeep = upkeep_resource(game)
    out: dict[str, float] = {}
    for k, h in spec.items():
        keys = ids if k == "all" else [upkeep] if k == "upkeep" else [k]
        for r in keys:
            if r in ids:
                out[r] = out.get(r, 0.0) + round(max(eco["gross"].get(r, 0.0), 1.0) * float(h))
    return out


async def _economy(game: Game, conn: asyncpg.Connection, v: VillageRow) -> dict[str, Any]:
    return game.engine.economy(game.engine.normalize(v.state), await hosted_upkeep(game, conn, v.id))


async def priced(game: Game, conn: asyncpg.Connection, v: VillageRow, ev: dict[str, Any]) -> dict[str, Any]:
    """The event as the player sees it: costs and gains in resources, and which choices are open."""
    eco = await _economy(game, conn, v)
    levels = _levels(v)
    choices = []
    for c in ev["choices"]:
        choices.append(c | {"cost": _hours_of(game, eco, c.get("cost", {})), "gain": _hours_of(game, eco, c.get("gain", {})),
                            "available": _ok(c.get("requires"), levels)})
    return {k: ev[k] for k in ("id", "title", "text", "default")} | {"choices": choices}


async def apply(game: Game, tx: Tx, v: VillageRow, ev: dict[str, Any], choice: dict[str, Any], forced: bool = False) -> dict[str, Any]:
    from . import gods
    from .contentment import add_effect, add_unrest, schedule_end

    await accrue(game, tx, v)
    eco = await _economy(game, tx.conn, v)
    cost = _hours_of(game, eco, choice.get("cost", {}))
    res = v.state["resources"]
    if not forced:
        if not _ok(choice.get("requires"), _levels(v)):
            raise rule("requirements_not_met")
        if any(res.get(k, 0) < n for k, n in cost.items()):
            raise rule("insufficient_resources")
        if choice.get("favor_cost") and gods.settle(game, v) < float(choice["favor_cost"]):
            raise rule("no_favor", f"{choice['favor_cost']} favor needed")
    for k, n in cost.items():
        res[k] = max(0.0, res.get(k, 0) - n)
    if choice.get("favor_cost"):
        gods.settle(game, v)
        v.meta["favor"] = max(0.0, v.meta["favor"] - float(choice["favor_cost"]))
    gain = _hours_of(game, eco, choice.get("gain", {}))
    for k, n in gain.items():
        res[k] = max(0.0, res.get(k, 0) + n)
    if choice.get("favor"):
        gods.settle(game, v)
        v.meta["favor"] = min(float(gods.cfg(game).get("max_favor", 500)), v.meta["favor"] + float(choice["favor"]))
    hours = float(choice.get("hours", 12))
    ends = []
    if choice.get("contentment"):
        ends.append(add_effect(game, v.meta, "contentment", ev["title"], float(choice["contentment"]), hours))
    if choice.get("boost"):
        ends.append(add_effect(game, v.meta, "boost", ev["title"], float(choice["boost"]), hours))
    if choice.get("unrest"):
        await add_unrest(game, tx, v, float(choice["unrest"]))
    artwork = None
    if choice.get("artwork"):
        from .artworks import commission

        artwork = await commission(game, tx, v, str(choice["artwork"]))  # the sculptor's work joins the city's finds
    v.meta.pop("omen", None)
    await refresh_boost(game, tx, v)
    await save_village(game, tx, v)
    for until in set(ends):
        await schedule_end(game, tx, until, village_id=v.id)
    outcome = {"event": ev["id"], "title": ev["title"], "choice": choice["id"], "label": choice["label"], "cost": cost, "gain": gain,
               "forced": forced, "village": v.public(), "artwork": artwork}
    title = f"{ev['title']}: {choice['label'].lower()}" + (f" – {artwork['name']}" if artwork else "") + (" (no answer came)" if forced else "")
    await add_report(game, tx, v.player_id, "omen", title, outcome)
    return outcome


@router.post("/villages/{village_id}/omen/{choice_id}")
async def answer(village_id: int, choice_id: str, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .villages import push_village

    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        o = v.meta.get("omen")
        ev = next((e for e in events(game) if o and e["id"] == o["id"]), None)
        if ev is None:
            raise not_found("no_omen")
        choice = next((c for c in ev["choices"] if c["id"] == choice_id), None)
        if choice is None:
            raise not_found("unknown_choice")
        await apply(game, tx, v, ev, choice)
        return await push_village(game, tx, v)


async def pick(game: Game, v: VillageRow, rng: random.Random) -> dict[str, Any] | None:
    from .calendar import when

    season = when(game).get("id")
    levels = _levels(v)
    pool = [e for e in events(game) if _ok(e.get("requires"), levels) and (not e.get("seasons") or season in e["seasons"])]
    return rng.choice(pool) if pool else None


async def omen_for(game: Game, tx: Tx, v: VillageRow, ev: dict[str, Any]) -> None:
    """Put an omen before a (locked) city's ruler."""
    from .villages import push_village

    expires = game.clock.now() + _ms(game, float(cfg(game).get("expire_hours", 12)))
    v.meta["omen"] = {"id": ev["id"], "at": game.clock.now(), "expires_at": expires}
    await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
    await game.schedule(tx, EXPIRE, expires, {"omen": ev["id"]}, village_id=v.id)
    game.event(tx, v.player_id, "omen.new", {"village": v.public(), "title": ev["title"], "expires_at": expires})
    await push_village(game, tx, v)


async def on_tick(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    c = cfg(game)
    rng = random.Random()
    now = game.clock.now()
    active_since = now - 3 * 86_400_000
    rows = await tx.conn.fetch(
        """SELECT v.id FROM villages v JOIN players p ON p.id = v.player_id
           WHERE NOT p.npc AND p.vacation_until <= $1 AND p.banned_until <= $1 AND coalesce(p.last_seen_at, 0) >= $2
             AND NOT (v.meta ? 'omen')""", now, active_since)
    for r in rows:
        if rng.random() >= float(c.get("chance", 0.35)):
            continue
        v = await get_village(tx.conn, r["id"], lock=True)
        ev = await pick(game, v, rng)
        if ev:
            await omen_for(game, tx, v, ev)
    await game.schedule(tx, TICK, now + _ms(game, float(c.get("every_hours", 6))), {})


async def on_expire(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    try:
        v = await get_village(tx.conn, job["village_id"], lock=True)
    except Exception:  # noqa: BLE001
        return
    o = v.meta.get("omen")
    if not o or o["id"] != job["payload"]["omen"] or o["expires_at"] > game.clock.now():
        return
    ev = next((e for e in events(game) if e["id"] == o["id"]), None)
    if ev is None:
        v.meta.pop("omen", None)
        await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
        return
    choice = next(c for c in ev["choices"] if c["id"] == ev["default"])
    await apply(game, tx, v, ev, choice, forced=True)
    await push_village(game, tx, v)


@hookimpl
async def ovian_started(game: Game) -> None:
    if not cfg(game):
        return
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", TICK):
            await game.schedule(tx, TICK, game.clock.now() + 5 * 60_000, {})


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    o = village.meta.get("omen")
    ev = next((e for e in events(game) if o and e["id"] == o["id"]), None)
    if ev:
        view["omen"] = await priced(game, conn, village, ev) | {"at": o["at"], "expires_at": o["expires_at"]}


module = Module("omens", router=router, jobs={TICK: on_tick, EXPIRE: on_expire})
