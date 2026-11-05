"""Contentment and unrest.

Each city has a contentment score, the sum of reasons its people give:

- culture (temples, theatres, universities): ``culture / culture_divisor``, up to ``culture_max``;
- amenities: buildings with a ``contentment`` effect (gardens, baths, games), up to ``amenities_max``;
- politics: techs researched in the city, listed in ``techs`` (see below);
- food: a surplus of the upkeep resource pleases, a deficit angers;
- size: big cities are harder to keep happy (``size_per_level`` per city-centre level);
- tribute: paying an overlord (``tribute``), or the mother city for a colony (``colony``);
- defeats: each lost battle in the last ``defeat_hours`` (``defeat`` each, down to ``defeat_max``);
- timed moods (omens, festivals, ...) kept on the city and on its player;
- whatever other modules return from ``ovian_contentment`` (governments, seasons).

A happy city produces up to 10% more (``bonus_per_point`` per point), an unhappy one
up to 40% less (``penalty_per_point``). Above ``defense_from`` points its citizens also take up arms when it is
attacked: ``defense_per_point`` of defense for each point over it, up to ``defense_max`` (+20% at 100). A vassal whose score is below ``rebel_below``
gathers unrest (one point per missing point per hour, at world speed); at
``rebel_at`` it rises up and throws off its overlord. Colonies never rebel.

Techs listed in ``techs`` change a city's politics once researched there. Each may give
``contentment`` points and multiply unrest growth (``unrest``), calming (``calm``), the
crowded-city penalty (``size``), the anger at paying tribute (``tribute``) and the unrest agitators
stir up (``agitators``); ``rebel_below`` is added to the threshold under which unrest gathers:

    techs:
      political_thought: { contentment: 3, unrest: 0.75 }
      law_code: { rebel_below: -5, calm: 1.5 }

Other modules add timed effects with ``add_effect``: ``kind`` "contentment" (points)
or "boost" (production fraction). They end by themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg

from ..hooks import hookimpl
from ..repo import VillageRow, get_village, hosted_upkeep, refresh_boost, save_village
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

TICK = "contentment.tick"
END = "effect.end"

DEFAULTS: dict[str, float] = {
    "base": 5, "culture_divisor": 5, "culture_max": 20, "amenities_max": 30, "food_surplus": 5, "food_deficit": -20, "size_per_level": -0.5,
    "tribute": -15, "colony": -5, "defeat": -5, "defeat_hours": 24, "defeat_max": -20,
    "bonus_per_point": 0.002, "bonus_max": 0.1, "penalty_per_point": 0.004, "penalty_max": 0.4,
    "rebel_below": -10, "rebel_at": 100, "calm_rate": 10, "tick_minutes": 30,
    "defense_from": 50, "defense_per_point": 0.004, "defense_max": 0.2,
}


def cfg(game: Game) -> dict[str, float]:
    c = game.content.extensions.get("contentment", {})
    return {k: float(c.get(k, v)) for k, v in DEFAULTS.items()}


MULTIPLIERS = ("unrest", "calm", "size", "tribute", "agitators")


def politics(game: Game, v: VillageRow) -> dict[str, Any]:
    """What the techs researched in a city do to its politics."""
    table = (game.content.extensions.get("contentment") or {}).get("techs") or {}
    out: dict[str, Any] = dict.fromkeys(MULTIPLIERS, 1.0) | {"rebel_below": 0.0, "points": []}
    names = {t["id"]: t["name"] for t in game.content.pack.get("techs", [])}
    for t in v.state.get("techs", []):
        fx = table.get(t)
        if not fx:
            continue
        for k in MULTIPLIERS:
            out[k] *= float(fx.get(k, 1.0))
        out["rebel_below"] += float(fx.get("rebel_below", 0))
        if fx.get("contentment"):
            out["points"].append((names.get(t, t), float(fx["contentment"])))
    from .governors import effects

    gov = effects(game, v)  # the governor's traits
    for k in MULTIPLIERS:
        out[k] *= gov[k]
    out["points"].extend(gov["points"])
    return out


def curve_at(c: Any, level: int) -> float:
    if level <= 0 or not c:
        return 0.0
    if isinstance(c, list):
        return float(c[min(level, len(c)) - 1])
    x = float(c["base"]) * float(c["factor"]) ** (level - 1)
    r = c.get("round")
    return round(x / r) * r if r else x


def amenities(game: Game, v: VillageRow, cap: float) -> list[tuple[str, float]]:
    """Contentment from buildings (gardens, baths, an embassy...), one line per kind, capped in total."""
    by: dict[str, float] = {}
    for s in v.state["slots"]:
        b = game.content.building(s.get("building") or "") if s.get("building") else None
        fx = ((b or {}).get("effects") or {}).get("contentment")
        if fx and s.get("level"):
            by[b["name"]] = by.get(b["name"], 0.0) + curve_at(fx, int(s["level"]))
    out = list(by.items())
    total = sum(by.values())
    if total > cap:
        out.append(("No more from buildings", cap - total))
    return out


def rebel_below(game: Game, v: VillageRow) -> float:
    return cfg(game)["rebel_below"] + politics(game, v)["rebel_below"]


def enabled(game: Game) -> bool:
    return game.content.extensions.get("contentment") is not None


def _hours(game: Game, h: float) -> int:
    return int(h * 3_600_000 / game.content.pack["world"]["speed"])


def add_effect(game: Game, meta: dict[str, Any], kind: str, label: str, value: float, hours: float) -> int:
    """Add a timed effect to a city's or player's ``meta``; returns when it ends."""
    now = game.clock.now()
    until = now + _hours(game, hours)
    fx = [e for e in meta.get("effects", []) if e["until"] > now]
    fx.append({"kind": kind, "label": label, "value": value, "until": until})
    meta["effects"] = fx
    return until


def active(game: Game, meta: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    now = game.clock.now()
    return [e for e in meta.get("effects", []) if e["kind"] == kind and e["until"] > now]


async def schedule_end(game: Game, tx: Tx, until: int, village_id: int | None = None, player_id: int | None = None) -> None:
    """Re-apply production when a timed effect runs out."""
    await game.schedule(tx, END, until + 1, {"player_id": player_id}, village_id=village_id)


def upkeep_resource(game: Game) -> str | None:
    return next((r["id"] for r in game.content.pack["resources"] if r.get("upkeep")), None)


def growth_level(game: Game, v: VillageRow) -> int:
    b = (game.content.pack["village"].get("growth") or {}).get("building")
    return max((s["level"] for s in v.state["slots"] if b and s.get("building") == b), default=0)


async def factors(game: Game, conn: asyncpg.Connection, v: VillageRow) -> list[tuple[str, float]]:
    c = cfg(game)
    pol = politics(game, v)
    out: list[tuple[str, float]] = [("Contented by nature", c["base"])]
    eco = game.engine.economy(game.engine.normalize(v.state), await hosted_upkeep(game, conn, v.id))
    if eco.get("culture"):
        out.append(("Culture", min(c["culture_max"], eco["culture"] / c["culture_divisor"])))
    if eco.get("contentment"):
        out.extend(amenities(game, v, c["amenities_max"]))
    out.extend(pol["points"])
    upkeep = upkeep_resource(game)
    if upkeep in eco["production"]:
        net = eco["production"][upkeep]
        out.append(("Food surplus", c["food_surplus"]) if net >= 0 else ("Hunger", c["food_deficit"]))
    lvl = growth_level(game, v)
    if lvl > 1:
        out.append(("A crowded city", round(lvl * c["size_per_level"] * pol["size"], 1)))
    if v.state.get("tribute"):
        out.append(("Colony of the mother city", c["colony"] * pol["tribute"]) if v.meta.get("mother_id")
                   else ("Tribute to an overlord", c["tribute"] * pol["tribute"]))
    now = game.clock.now()
    window = _hours(game, c["defeat_hours"])
    defeats = [t for t in v.meta.get("defeats", []) if t > now - window]
    if defeats:
        out.append(("Lost battles", max(c["defeat_max"], len(defeats) * c["defeat"])))
    for e in active(game, v.meta, "contentment"):
        out.append((e["label"], float(e["value"])))
    pmeta = await conn.fetchval("SELECT meta FROM players WHERE id = $1", v.player_id) or {}
    for e in active(game, pmeta, "contentment"):
        out.append((e["label"], float(e["value"])))
    for res in await game.emit("ovian_contentment", game=game, conn=conn, village=v):
        out.extend(res or [])
    return [(label, round(n, 1)) for label, n in out if n]


def effect_of(game: Game, score: float) -> float:
    c = cfg(game)
    if score >= 0:
        return min(c["bonus_max"], score * c["bonus_per_point"])
    return max(-c["penalty_max"], score * c["penalty_per_point"])


def defense_of(game: Game, score: float) -> float:
    """Defense a content city's citizens add when it is attacked, as a fraction."""
    c = cfg(game)
    return round(min(c["defense_max"], max(0.0, score - c["defense_from"]) * c["defense_per_point"]), 4)


async def score(game: Game, conn: asyncpg.Connection, v: VillageRow) -> tuple[float, list[tuple[str, float]]]:
    f = await factors(game, conn, v)
    return max(-100.0, min(100.0, sum(n for _, n in f))), f


def can_rebel(v: VillageRow) -> bool:
    return bool(v.state.get("tribute")) and not v.meta.get("mother_id")


async def unrest_now(game: Game, conn: asyncpg.Connection, v: VillageRow, s: float | None = None) -> float:
    """Unrest settled up to now (not saved)."""
    c = cfg(game)
    now = game.clock.now()
    have = float(v.meta.get("unrest", 0))
    since = int(v.meta.get("unrest_at", now))
    hours = max(0, now - since) / 3_600_000 * game.content.pack["world"]["speed"]
    if s is None:
        s, _ = await score(game, conn, v)
    pol = politics(game, v)
    below = c["rebel_below"] + pol["rebel_below"]
    if can_rebel(v) and s < below:
        return have + (below - s) * pol["unrest"] * hours
    return max(0.0, have - c["calm_rate"] * pol["calm"] * hours)


async def add_unrest(game: Game, tx: Tx, v: VillageRow, points: float) -> float:
    """Stir up a (locked) city; it may rise up at once."""
    u = await unrest_now(game, tx.conn, v) + points
    v.meta["unrest"], v.meta["unrest_at"] = u, game.clock.now()
    await _maybe_rise(game, tx, v)
    return u


async def _maybe_rise(game: Game, tx: Tx, v: VillageRow) -> bool:
    if not can_rebel(v) or float(v.meta.get("unrest", 0)) < cfg(game)["rebel_at"]:
        return False
    from .submission import release

    v.meta["unrest"] = 0.0
    await tx.conn.execute("UPDATE villages SET meta = $2 WHERE id = $1", v.id, v.meta)
    await release(game, tx, v, reason="uprising")
    return True


async def settle(game: Game, tx: Tx, v: VillageRow) -> bool:
    """Bring a locked city's unrest and production up to date. Returns True if it changed."""
    from .villages import push_village

    s, _ = await score(game, tx.conn, v)
    u = await unrest_now(game, tx.conn, v, s)
    old_boost = v.state.get("boost", 0.0)
    v.meta["unrest"], v.meta["unrest_at"] = round(u, 3), game.clock.now()
    if await _maybe_rise(game, tx, v):
        v = await get_village(tx.conn, v.id, lock=True)
    await refresh_boost(game, tx, v)
    await save_village(game, tx, v)
    changed = abs(v.state.get("boost", 0.0) - old_boost) > 1e-6
    if changed:
        await push_village(game, tx, v)
    return changed


async def on_tick(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    ids = await tx.conn.fetch("SELECT v.id FROM villages v JOIN players p ON p.id = v.player_id WHERE NOT p.npc ORDER BY v.id")
    for r in ids:
        v = await get_village(tx.conn, r["id"], lock=True)
        await settle(game, tx, v)
    await game.schedule(tx, TICK, game.clock.now() + int(cfg(game)["tick_minutes"] * 60_000), {})


async def on_end(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from ..repo import refresh_all

    if job["village_id"]:
        try:
            v = await get_village(tx.conn, job["village_id"], lock=True)
        except Exception:  # noqa: BLE001 - gone
            return
        now = game.clock.now()
        v.meta["effects"] = [e for e in v.meta.get("effects", []) if e["until"] > now]
        await settle(game, tx, v)
    elif job["payload"].get("player_id"):
        await refresh_all(game, job["payload"]["player_id"], tx=tx)


# ---------------------------------------------------------------------- hooks


@hookimpl
async def ovian_started(game: Game) -> None:
    if not enabled(game):
        return
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", TICK):
            await game.schedule(tx, TICK, game.clock.now() + 60_000, {})


@hookimpl
async def ovian_boost(game: Game, conn: asyncpg.Connection, village: VillageRow) -> float:
    total = sum(float(e["value"]) for e in active(game, village.meta, "boost"))
    if enabled(game) and not village.meta.get("camp"):
        s, _ = await score(game, conn, village)
        total += effect_of(game, s)
    return total


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    if not enabled(game) or defender.meta.get("camp"):
        return
    s, _ = await score(game, tx.conn, defender)
    d = defense_of(game, s)
    if d:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d
        battle.setdefault("modifiers", {})["contentment_defense"] = d


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    if not enabled(game) or not result["attacker_won"] or defender.meta.get("camp"):
        return
    now = game.clock.now()
    window = _hours(game, cfg(game)["defeat_hours"])
    defender.meta["defeats"] = [t for t in defender.meta.get("defeats", []) if t > now - window][-9:] + [now]
    await tx.conn.execute("UPDATE villages SET meta = jsonb_set(meta, '{defeats}', $2) WHERE id = $1", defender.id, defender.meta["defeats"])


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    if enabled(game):
        await refresh_boost(game, tx, village)
        await tx.conn.execute("UPDATE villages SET state = $2 WHERE id = $1", village.id, village.state)


@hookimpl
async def ovian_build_demolished(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    await ovian_build_completed(game, tx, village, building, level)


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    now = game.clock.now()
    fx = [e for e in village.meta.get("effects", []) if e["until"] > now]
    if not enabled(game):
        if fx:
            view["contentment"] = {"effects": fx}
        return
    c = cfg(game)
    s, f = await score(game, conn, village)
    pol = politics(game, village)
    view["contentment"] = {
        "score": round(s, 1),
        "factors": [{"label": label, "value": n} for label, n in f],
        "production": round(effect_of(game, s), 4),
        "defense": defense_of(game, s),
        "defense_from": c["defense_from"],
        "unrest": round(await unrest_now(game, conn, village, s), 1),
        "rebel_at": c["rebel_at"],
        "rebel_below": c["rebel_below"] + pol["rebel_below"],
        "politics": {k: round(pol[k], 3) for k in (*MULTIPLIERS, "rebel_below") if pol[k] != (0.0 if k == "rebel_below" else 1.0)},
        "can_rebel": can_rebel(village),
        "effects": fx,
    }


module = Module("contentment", jobs={TICK: on_tick, END: on_end})
