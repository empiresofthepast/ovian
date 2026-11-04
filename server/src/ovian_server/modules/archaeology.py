"""Archaeology: every building site remembers what stood on it, and digging brings it back.

**Layers.** When a building is pulled down, or an overlord's building falls to ruin when its vassal
breaks free, the site keeps it as a layer (``meta.strata``): what it was, in whose style, how high
it stood, who founded it and when, and how it ended. Below all of them, ``ancient_chance`` of the
sites hide the remains of a people from before history (``ancient``), the same for every world seed.

**Digging** (``POST /villages/{id}/sites/{slot}/excavate``) works on an empty center or foreign
site, or on a ruin. It costs ``cost`` and takes ``hours`` (at world speed). It uncovers the top layer
not yet dug, or, when the known layers are done, probes for the ancient one: a site found empty is
*probed* and cannot be dug again. Digging a ruin clears its site.

**Finds.** Every layer gives one find, graded ``common``, ``fine`` or ``exceptional`` (``grades``:
chance and culture). Its name comes from ``finds`` (by building, ``default`` otherwise) or the ancient
people's list. A find is kept in a city of its finder; the best ``display.per_level`` × levels of the
``display`` building (temples) are shown there and add their culture. Finds can be moved between your
own cities. Each one carries its full context, so it can travel to other games (a museum...):
``GET /api/v1/finds`` is the public catalogue of a world, ``GET /api/v1/finds/{id}`` one record.

    extensions:
      archaeology: { cost: {...}, hours: 2, ancient_chance: 0.4, display: { building: temple, per_level: 1 },
                     grades: { common: { chance: 0.65, culture: 1 }, ... }, ancient: [...], finds: {...} }
"""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_player, lock_villages, own_village, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

DIG = "dig.complete"
FORMAT = "ovian-find/1"
router = APIRouter(tags=["archaeology"])


def cfg(game: Game) -> dict[str, Any] | None:
    return game.content.extensions.get("archaeology")


def _ms(game: Game, hours: float) -> int:
    return int(float(hours) * 3_600_000 / game.content.pack["world"]["speed"])


def _center(game: Game, v: VillageRow, slot: int) -> bool:
    """A town or foreign-quarter site (fields have no layers)."""
    fields = len(game.content.pack["village"]["field_slots"])
    slots = v.state["slots"]
    if slot < fields or slot >= len(slots):
        return False
    return slot < fields + int(game.content.pack["village"]["center_slots"]) or bool(slots[slot].get("foreign"))


# ------------------------------------------------------------------ layers


def strata(v: VillageRow, slot: int) -> list[dict[str, Any]]:
    return (v.meta.get("strata") or {}).get(str(slot), [])


def founded(game: Game, v: VillageRow, slot: int, player_id: int | None) -> None:
    """Remember when and by whom the building on ``slot`` was founded (its first level finished)."""
    v.meta.setdefault("founded", {})[str(slot)] = {"at": game.clock.now(), "by": player_id}


def bury(game: Game, v: VillageRow, slot: int, site: dict[str, Any], end: str, by: int | None = None) -> None:
    """``site`` ends (``demolished``, ``ruined``): it becomes a layer of ``slot``. Call before clearing the slot."""
    if cfg(game) is None or not site.get("building") or not int(site.get("level") or 0) or not _center(game, v, slot):
        return
    if site["building"] == (game.content.extensions.get("embassies") or {}).get("ruin", "ruin"):
        return  # a ruin is the end of the layer below it, not a layer of its own
    start = (v.meta.get("founded") or {}).pop(str(slot), None) or {}
    layer = {"building": site["building"], "level": int(site["level"]), "style": site.get("style"),
             "from": start.get("at"), "to": game.clock.now(), "built_by": start.get("by") or by, "end": end}
    v.meta.setdefault("strata", {}).setdefault(str(slot), []).append(layer)


def ancient(game: Game, v: VillageRow, slot: int) -> dict[str, Any] | None:
    """The prehistoric layer under a site, if any: fixed by the city and the site."""
    c = cfg(game) or {}
    peoples = c.get("ancient") or []
    if not peoples:
        return None
    h = hashlib.sha256(f"{v.id}:{slot}:{game.settings.world_id}".encode()).digest()
    if h[0] / 256 >= float(c.get("ancient_chance", 0.4)):
        return None
    return peoples[h[1] % len(peoples)]


def probed(v: VillageRow, slot: int) -> bool:
    return str(slot) in (v.meta.get("probed") or [])


def undug(v: VillageRow, slot: int) -> list[dict[str, Any]]:
    return [x for x in strata(v, slot) if not x.get("dug")]


# ------------------------------------------------------------------ finds


def _grade(game: Game, rnd: random.Random) -> tuple[str, float]:
    grades = (cfg(game) or {}).get("grades") or {"common": {"chance": 1, "culture": 1}}
    roll = rnd.random() * sum(float(g.get("chance", 0)) for g in grades.values())
    for name, g in grades.items():
        roll -= float(g.get("chance", 0))
        if roll <= 0:
            return name, float(g.get("culture", 0))
    name = next(iter(grades))
    return name, float(grades[name].get("culture", 0))


def _name(game: Game, layer: dict[str, Any], rnd: random.Random) -> str:
    c = cfg(game) or {}
    if layer.get("ancient"):
        pool = next((a.get("finds") for a in c.get("ancient", []) if a["id"] == layer["ancient"]), None)
    else:
        pool = (c.get("finds") or {}).get(layer.get("building") or "")
    pool = pool or (c.get("finds") or {}).get("default") or ["potsherds"]
    n = str(rnd.choice(pool))
    return n[:1].upper() + n[1:]


def find_view(game: Game, r: asyncpg.Record | dict[str, Any], owner: str | None = None, kept: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": r["id"], "format": FORMAT, "uri": f"ovian://{game.settings.world_id}/finds/{r['id']}", "name": r["name"],
            "grade": r["grade"], "culture": r["culture"], "found_at": r["found_at"], "found_by": r["found_by"],
            "owner": {"player_id": r["player_id"], "name": owner} if r["player_id"] else None,
            "kept_in": kept, "context": r["context"]}


async def _layer_context(game: Game, conn: asyncpg.Connection, v: VillageRow, slot: int, layer: dict[str, Any], depth: int) -> dict[str, Any]:
    out = dict(layer)
    out.pop("dug", None)
    if layer.get("building"):
        b = game.content.building(layer["building"]) or {}
        out["building_name"] = b.get("name", layer["building"])
    if layer.get("style"):
        out["style_name"] = (game.content.tribe(layer["style"]) or {}).get("name", layer["style"])
    if layer.get("built_by"):
        out["built_by_name"] = await conn.fetchval("SELECT username FROM players WHERE id = $1", layer["built_by"])
    return {"world": game.settings.world_id, "pack": game.content.pack.get("id"),
            "site": {"village_id": v.id, "village": v.name, "x": v.x, "y": v.y, "slot": slot},
            "depth": depth, "layer": out}


async def sync_display(game: Game, tx: Tx, v: VillageRow) -> None:
    """Show the best finds kept in ``v`` in its temples and set the culture they give. Saves nothing."""
    c = cfg(game)
    if c is None:
        return
    d = c.get("display") or {}
    room = sum(int(s.get("level") or 0) for s in v.state["slots"] if s.get("building") == d.get("building", "temple")) * int(d.get("per_level", 1))
    rows = await tx.conn.fetch("SELECT culture FROM finds WHERE village_id = $1 ORDER BY culture DESC, id LIMIT $2", v.id, room) if room else []
    total = round(sum(float(r["culture"]) for r in rows), 3)
    if abs(float(v.state.get("culture_relics", 0.0)) - total) < 1e-9:
        return
    await accrue(game, tx, v)
    if total:
        v.state["culture_relics"] = total
    else:
        v.state.pop("culture_relics", None)


# ------------------------------------------------------------------ orders


async def _jobs(conn: asyncpg.Connection, village_id: int) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT id, due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2 ORDER BY due_at", village_id, DIG)


@router.post("/villages/{village_id}/sites/{slot}/excavate")
async def excavate(village_id: int, slot: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Dig an empty site or a ruin: what lies below comes up as a find, kept in this city."""
    from .embassies import reserved
    from .villages import BUILD, push_village, spend

    c = cfg(game)
    if c is None:
        raise rule("no_archaeology", "this world has no archaeology")
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        if not _center(game, v, slot):
            raise rule("invalid_slot", "only building sites in the town can be dug")
        site = v.state["slots"][slot]
        ruin = (game.content.extensions.get("embassies") or {}).get("ruin", "ruin")
        if site.get("building") not in (None, ruin):
            raise rule("site_taken", "pull the building down first, or dig an empty site")
        if slot in reserved(v) and not reserved(v)[slot].get("until"):  # a past overlord's site may be dug
            raise rule("overlord_site", "this site belongs to your overlord")
        if await tx.conn.fetchval("SELECT 1 FROM jobs WHERE village_id = $1 AND kind = $2 AND (payload->>'slot')::int = $3",
                                  v.id, BUILD, slot):
            raise rule("site_busy", "something is being built on this site")
        if any(j["payload"]["slot"] == slot for j in await _jobs(tx.conn, v.id)):
            raise rule("site_busy", "the diggers are already at work here")
        if not undug(v, slot) and probed(v, slot):
            raise rule("nothing_left", "this site has been dug down to the bare rock")
        cost = {r: float(n) for r, n in (c.get("cost") or {}).items()}
        if not all(v.state["resources"].get(r, 0) >= n for r, n in cost.items()):
            raise rule("insufficient_resources")
        spend(v, cost)
        due = game.clock.now() + _ms(game, float(c.get("hours", 2)))
        await game.schedule(tx, DIG, due, {"slot": slot, "cost": cost, "started_at": game.clock.now(), "player_id": player_id}, village_id=v.id)
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


@router.delete("/villages/{village_id}/sites/{slot}/excavate")
async def stop_digging(village_id: int, slot: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Call the diggers off: the cost comes back."""
    from .villages import push_village, refund

    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        job = next((j for j in await _jobs(tx.conn, v.id) if j["payload"]["slot"] == slot), None)
        if job is None:
            raise not_found("no_dig")
        await accrue(game, tx, v)
        refund(game, v, job["payload"].get("cost") or {})
        await tx.conn.execute("DELETE FROM jobs WHERE id = $1", job["id"])
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


async def on_dig(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .chronicle import record
    from .villages import push_village

    got = await lock_villages(tx.conn, job["village_id"]) if job["village_id"] else {}
    v = got.get(job["village_id"])
    if v is None:
        return
    await accrue(game, tx, v, at=job["due_at"])
    slot = int(job["payload"]["slot"])
    rnd = random.Random(f"{game.settings.world_id}:{v.id}:{slot}:{job['id']}")
    layers = undug(v, slot)
    layer: dict[str, Any] | None = None
    depth = 0
    if layers:
        top = layers[-1]
        top["dug"] = True
        depth = len(strata(v, slot)) - strata(v, slot).index(top)
        layer = {k: top.get(k) for k in ("building", "level", "style", "from", "to", "built_by", "end")}
    elif not probed(v, slot):
        v.meta.setdefault("probed", []).append(str(slot))
        a = ancient(game, v, slot)
        if a:
            depth = len(strata(v, slot)) + 1
            layer = {"ancient": a["id"], "people": a.get("name"), "age": a.get("age")}
    ruin = (game.content.extensions.get("embassies") or {}).get("ruin", "ruin")
    site = v.state["slots"][slot] if slot < len(v.state["slots"]) else {}
    if site.get("building") == ruin:  # the ruin is cleared by the dig
        v.state["slots"][slot] = {"building": None, "level": 0} | ({"foreign": True} if site.get("foreign") else {})
    finder = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", v.player_id) or "?"
    find = None
    if layer is not None:
        grade, culture = _grade(game, rnd)
        context = await _layer_context(game, tx.conn, v, slot, layer, depth)
        row = await tx.conn.fetchrow(
            """INSERT INTO finds(player_id, village_id, name, grade, culture, context, found_at, found_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
            v.player_id, v.id, _name(game, layer, rnd), grade, culture, context, job["due_at"], finder)
        find = find_view(game, row, finder, v.public())
        await sync_display(game, tx, v)
        if grade != "common":
            await record(game, tx, "find", f"{finder} unearthed {find['name'].lower()} ({grade}) in {v.name}", village=v,
                         data={"find_id": row["id"], "grade": grade})
    await save_village(game, tx, v)
    title = f"Diggers in {v.name}: " + (f"{find['name']} ({find['grade']})" if find else "nothing but bare rock")
    await add_report(game, tx, v.player_id, "excavation", title, {"village": v.public(), "slot": slot, "find": find})
    game.event(tx, v.player_id, "excavation.done", {"village_id": v.id, "slot": slot, "find": find})
    await push_village(game, tx, v)


class MoveFind(BaseModel):
    village_id: int


@router.post("/finds/{find_id}/move")
async def move_find(find_id: int, body: MoveFind, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Keep one of your finds in another of your cities."""
    async with game.tx() as tx:
        r = await tx.conn.fetchrow("SELECT * FROM finds WHERE id = $1 AND player_id = $2 FOR UPDATE", find_id, player_id)
        if r is None:
            raise not_found("find_not_found")
        dest = await own_village(tx.conn, body.village_id, player_id)
        ids = [i for i in (r["village_id"], dest.id) if i]
        got = await lock_villages(tx.conn, *ids)
        await tx.conn.execute("UPDATE finds SET village_id = $2 WHERE id = $1", find_id, dest.id)
        for v in got.values():
            await sync_display(game, tx, v)
            await save_village(game, tx, v)
        name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
        return find_view(game, {**dict(r), "village_id": dest.id}, name, dest.public())


async def _finds(game: Game, conn: asyncpg.Connection, where: str, *args: Any, limit: int = 100) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        f"""SELECT f.*, p.username AS owner, v.id AS v_id, v.name AS v_name, v.x AS v_x, v.y AS v_y, v.player_id AS v_player
            FROM finds f LEFT JOIN players p ON p.id = f.player_id LEFT JOIN villages v ON v.id = f.village_id
            WHERE {where} ORDER BY f.id DESC LIMIT {int(limit)}""", *args)
    return [find_view(game, r, r["owner"], {"id": r["v_id"], "name": r["v_name"], "x": r["v_x"], "y": r["v_y"], "player_id": r["v_player"]}
                      if r["v_id"] else None) for r in rows]


@router.get("/me/finds")
async def my_finds(player_id: PlayerId, game: GameDep) -> list[dict[str, Any]]:
    async with game.pool.acquire() as conn:
        return await _finds(game, conn, "f.player_id = $1", player_id, limit=1000)


@router.get("/finds")
async def catalogue(game: GameDep, before: int | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    """The public catalogue of this world's finds, newest first (``before``: page by id). No login needed."""
    async with game.pool.acquire() as conn:
        items = await _finds(game, conn, "($1::bigint IS NULL OR f.id < $1)", before, limit=limit)
    return {"format": FORMAT, "world": game.settings.world_id, "items": items, "next": items[-1]["id"] if len(items) == limit else None}


@router.get("/finds/{find_id}")
async def one_find(find_id: int, game: GameDep) -> dict[str, Any]:
    async with game.pool.acquire() as conn:
        got = await _finds(game, conn, "f.id = $1", find_id, limit=1)
    if not got:
        raise not_found("find_not_found")
    return got[0]


# ------------------------------------------------------------------ hooks


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    if cfg(game) and building == ((cfg(game) or {}).get("display") or {}).get("building", "temple"):
        await sync_display(game, tx, village)
        await save_village(game, tx, village)


@hookimpl
async def ovian_build_demolished(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    await ovian_build_completed(game, tx, village, building, level)


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    if order.get("type") == "build" and cfg(game) and any(j["payload"]["slot"] == order.get("slot") for j in await _jobs(tx.conn, village.id)):
        raise rule("site_busy", "the diggers are at work on this site")


@hookimpl
async def ovian_started(game: Game) -> None:
    """Ruins left before archaeology existed get the layer they stand for (an overlord's building)."""
    c = cfg(game)
    e = game.content.extensions.get("embassies") or {}
    if c is None or not e:
        return
    async with game.tx() as tx:
        ids = await tx.conn.fetch("SELECT id FROM villages WHERE state->'slots' @> $1::jsonb", [{"building": e.get("ruin", "ruin")}])
        for r in ids:
            v = (await lock_villages(tx.conn, r["id"]))[r["id"]]
            changed = False
            for i, s in enumerate(v.state["slots"]):
                if s.get("building") != e.get("ruin", "ruin") or strata(v, i):
                    continue
                q = next((q for q in v.meta.get("foreign", []) if q.get("embassy") == i or i in q.get("lord_sites", [])), None)
                what = e.get("building", "embassy") if q and q.get("embassy") == i else "ruin"
                v.meta.setdefault("strata", {})[str(i)] = [{"building": what, "level": 1, "style": s.get("style"), "from": (q or {}).get("since"),
                                                            "to": (q or {}).get("until"), "built_by": (q or {}).get("player_id"), "end": "ruined"}]
                changed = True
            if changed:
                await save_village(game, tx, v)


@hookimpl
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    c = cfg(game)
    if c is None:
        return
    fields = len(game.content.pack["village"]["field_slots"])
    sites: dict[str, Any] = {}
    for i in range(fields, len(village.state["slots"])):
        if not _center(game, village, i):
            continue
        known = strata(village, i)
        if known or probed(village, i):
            sites[str(i)] = {"layers": [{k: x.get(k) for k in ("building", "style", "level", "end", "from", "to")} | {"dug": bool(x.get("dug"))}
                                        for x in known],
                             "probed": probed(village, i)}
    digs = [{"id": j["id"], "slot": j["payload"]["slot"], "started_at": j["payload"].get("started_at"), "due_at": j["due_at"]}
            for j in await _jobs(conn, village.id)]
    finds = await _finds(game, conn, "f.village_id = $1", village.id, limit=500)
    d = c.get("display") or {}
    room = sum(int(s.get("level") or 0) for s in village.state["slots"] if s.get("building") == d.get("building", "temple")) * int(d.get("per_level", 1))
    shown = sorted(finds, key=lambda f: (-f["culture"], f["id"]))[:room]
    view["archaeology"] = {"cost": c.get("cost") or {}, "hours": float(c.get("hours", 2)), "sites": sites, "digs": digs,
                           "finds": finds, "display": {"building": d.get("building", "temple"), "room": room,
                                                       "shown": [f["id"] for f in shown],
                                                       "culture": float(village.state.get("culture_relics", 0.0))}}


module = Module("archaeology", router=router, jobs={DIG: on_dig})
