"""Villages: state view, construction and training."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from ovian_engine import PlanError
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import GameError, not_found, rule
from ..repo import VillageRow, accrue, get_player, hosted_upkeep, own_village, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

BUILD = "build.complete"
TRAIN = "train.unit"
RESEARCH = "research.complete"

router = APIRouter(tags=["villages"])


# --------------------------------------------------------------------- views


async def village_view(game: Game, conn: asyncpg.Connection, v: VillageRow) -> dict[str, Any]:
    """Everything the owner sees about a village, with resources accrued to now."""
    now = game.clock.now()
    extra = await hosted_upkeep(game, conn, v.id)
    state = game.engine.accrue(game.engine.normalize(v.state), now, extra)
    jobs = await conn.fetch(
        "SELECT id, kind, due_at, payload FROM jobs WHERE village_id = $1 AND kind = ANY($2::text[]) ORDER BY due_at, id",
        v.id, [BUILD, TRAIN, RESEARCH],
    )
    build_queue = [
        {"id": j["id"], "slot": p["slot"], "building": p["building"], "level": p["level"], "started_at": p["started_at"], "due_at": j["due_at"]}
        for j in jobs if j["kind"] == BUILD for p in [j["payload"]]
    ]
    training = [
        {"id": j["id"], "unit": p["unit"], "building": p["building"], "remaining": p["remaining"], "each_ms": p["each_ms"],
         "next_at": j["due_at"], "finishes_at": p["finishes_at"]}
        for j in jobs if j["kind"] == TRAIN for p in [j["payload"]]
    ]
    research = [
        {"id": j["id"], "tech": p["tech"], "started_at": p["started_at"], "due_at": j["due_at"]}
        for j in jobs if j["kind"] == RESEARCH for p in [j["payload"]]
    ]
    moves = await conn.fetch(
        """SELECT m.*, f.name AS from_name, f.x AS from_x, f.y AS from_y, f.player_id AS from_player,
                  t.name AS to_name, t.x AS to_x, t.y AS to_y, t.player_id AS to_player
           FROM movements m JOIN villages f ON f.id = m.from_id JOIN villages t ON t.id = m.to_id
           WHERE m.home_id = $1 OR m.to_id = $1 ORDER BY m.arrives_at""",
        v.id,
    )
    outgoing, incoming = [], []
    for m in moves:
        item = {
            "id": m["id"], "kind": m["kind"], "departs_at": m["departs_at"], "arrives_at": m["arrives_at"],
            "from": {"id": m["from_id"], "name": m["from_name"], "x": m["from_x"], "y": m["from_y"], "player_id": m["from_player"]},
            "to": {"id": m["to_id"], "name": m["to_name"], "x": m["to_x"], "y": m["to_y"], "player_id": m["to_player"]},
        }
        if m["home_id"] == v.id:
            outgoing.append(item | {"units": m["units"], "loot": m["loot"], "mission": m["mission"]})
        else:
            hostile = m["kind"] in ("attack", "raid")
            incoming.append(item | ({} if hostile else {"units": m["units"]}))
    here = await conn.fetch(
        "SELECT s.id, s.units, h.id AS vid, h.name, h.x, h.y, h.player_id FROM stationed s JOIN villages h ON h.id = s.home_id WHERE s.host_id = $1",
        v.id,
    )
    abroad = await conn.fetch(
        "SELECT s.id, s.units, h.id AS vid, h.name, h.x, h.y, h.player_id FROM stationed s JOIN villages h ON h.id = s.host_id WHERE s.home_id = $1",
        v.id,
    )
    pub = lambda r: {"id": r["vid"], "name": r["name"], "x": r["x"], "y": r["y"], "player_id": r["player_id"]}  # noqa: E731
    view = {
        **v.public(),
        "population": v.population,
        "state": state,
        "economy": game.engine.economy(state, extra),
        # Upkeep paid for foreign troops stationed here; clients pass it to Engine.accrue.
        "hosted_upkeep": extra,
        "build_queue": build_queue,
        "training": training,
        "research": research,
        "movements": {"outgoing": outgoing, "incoming": incoming},
        "reinforcements": {
            "here": [{"id": r["id"], "units": r["units"], "home": pub(r)} for r in here],
            "abroad": [{"id": r["id"], "units": r["units"], "host": pub(r)} for r in abroad],
        },
        "server_time": now,
    }
    await game.emit("ovian_village_view", game=game, conn=conn, village=v, view=view)
    return view


async def push_village(game: Game, tx: Tx, v: VillageRow) -> dict[str, Any]:
    """Send the owner a fresh view of the village after commit, and return it."""
    view = await village_view(game, tx.conn, v)
    game.event(tx, v.player_id, "village.updated", view)
    return view


async def style_of(conn: asyncpg.Connection, v: VillageRow, own_tribe: str) -> str:
    """The architecture a new building takes: its overlord's for a vassal, its owner's otherwise."""
    if v.state.get("tribute") and not v.meta.get("mother_id"):
        lord = await conn.fetchval(
            "SELECT p.tribe FROM vassals s JOIN villages o ON o.id = s.overlord_id JOIN players p ON p.id = o.player_id WHERE s.vassal_id = $1", v.id)
        if lord:
            return str(lord)
    return own_tribe


def spend(v: VillageRow, cost: dict[str, float]) -> None:
    res = v.state["resources"]
    for r, c in cost.items():
        res[r] = res.get(r, 0) - c


def refund(game: Game, v: VillageRow, amount: dict[str, float]) -> None:
    v.state = game.engine.deposit(v.state, amount)


def plan(fn: Any, *args: Any) -> dict[str, Any]:
    try:
        return fn(*args)
    except PlanError as e:
        raise rule(str(e.args[0])) from e


# -------------------------------------------------------------------- routes


@router.get("/villages/{village_id}")
async def get_village_view(village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id)
        return await village_view(game, tx.conn, v)


@router.get("/villages/{village_id}/options")
async def options(village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """What this city can do next: upgrades per site, new buildings for a free site, units and
    techs, each with its cost and time or the reason it is blocked (``blocked``). For scripts and
    AI assistants; the order endpoints check everything again."""
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id)
        await accrue(game, tx, v)
        player = await get_player(tx.conn, player_id)
        jobs = await build_jobs(tx.conn, v.id)
        queue = [{"slot": j["payload"]["slot"], "building": j["payload"]["building"], "level": j["payload"]["level"]} for j in jobs]
        have = v.state["resources"]
        affordable = lambda cost: all(have.get(r, 0) >= c for r, c in cost.items())  # noqa: E731

        async def check(kind: str, fn: Any, *args: Any) -> dict[str, Any]:
            try:
                p = fn(*args)
            except PlanError as e:
                return {"blocked": str(e.args[0])}
            try:
                async with tx.conn.transaction():  # validation hooks only read; roll back to be safe
                    await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v, order={"type": kind, **p})
                    raise _Rollback
            except _Rollback:
                pass
            except GameError as e:
                return {"blocked": e.code, "why": e.message} | {k: p[k] for k in ("cost",) if k in p}
            return p | {"affordable": affordable(p.get("cost", {}))}

        upgrades, free = [], []
        fields = len(game.content.pack["village"].get("field_slots", []))
        open_sites = game.engine.economy(v.state, await hosted_upkeep(game, tx.conn, v.id))["center_sites"]
        queued_sites = {q["slot"] for q in queue}
        foreign_free = []
        for i, slot in enumerate(v.state["slots"]):
            if slot.get("building") is None:
                if i in queued_sites:
                    continue
                if slot.get("foreign"):
                    from .embassies import reserved

                    if i not in reserved(v):  # overlord sites are never the owner's to build on
                        foreign_free.append(i)
                elif i < fields + open_sites:
                    free.append(i)
                continue
            r = await check("build", game.engine.plan_build, v.state, queue, i, None)
            if r.get("blocked") in ("max_level", "site_locked"):
                continue
            target = r.pop("level", None)
            upgrades.append({"slot": i, "building": slot["building"], "level": slot["level"], "to_level": target} | r)
        new = []
        for b in game.content.pack["buildings"]:
            site = (foreign_free if b.get("foreign") else free)[:1]
            if b.get("slot") == "field" or not site:
                continue
            r = await check("build", game.engine.plan_build, v.state, queue, site[0], b["id"])
            new.append({"building": b["id"], "name": b["name"]} | ({"foreign": True} if b.get("foreign") else {}) | r)
        units = []
        for u in game.content.pack["units"]:
            if u.get("tribe") not in (None, player["tribe"]):
                continue
            r = await check("train", game.engine.plan_training, v.state, player["tribe"], u["id"], 1)
            units.append({"unit": u["id"], "name": u["name"], "building": u.get("building")} | r)
        rjobs = await tx.conn.fetch("SELECT payload FROM jobs WHERE village_id = $1 AND kind = $2", v.id, RESEARCH)
        queued = [j["payload"]["tech"] for j in rjobs]
        techs = []
        for t in game.content.pack.get("techs", []):
            if t["id"] in v.state.get("techs", []):
                continue
            r = await check("research", game.engine.plan_research, v.state, queued, t["id"])
            techs.append({"tech": t["id"], "name": t["name"]} | r)
    return {"resources": have, "free_sites": free, "foreign_sites": foreign_free, "locked_sites": max(0, len(v.state["slots"]) - fields - open_sites), "upgrades": upgrades, "new_buildings": new, "units": units, "techs": techs}


class _Rollback(Exception):
    pass


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@router.patch("/villages/{village_id}")
async def rename(village_id: int, body: Rename, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        v.name = body.name.strip()
        await save_village(game, tx, v)
        tx.publish(game.topics.map, {"type": "map.village_changed", "at": game.clock.now(), "data": v.public()})
        return await push_village(game, tx, v)


class BuildOrder(BaseModel):
    slot: int = Field(ge=0, description="Slot index: field slots first, then center slots.")
    building: str | None = Field(None, description="Required when constructing on an empty center slot.")


async def build_jobs(conn: asyncpg.Connection, village_id: int) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT id, due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2 ORDER BY due_at, id", village_id, BUILD)


@router.post("/villages/{village_id}/build")
async def build(village_id: int, order: BuildOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        jobs = [j for j in await build_jobs(tx.conn, v.id) if not j["payload"].get("paid_by") or j["payload"]["slot"] == order.slot]
        queue = [{"slot": j["payload"]["slot"], "building": j["payload"]["building"], "level": j["payload"]["level"]} for j in jobs]
        p = plan(game.engine.plan_build, v.state, queue, order.slot, order.building)
        player = await get_player(tx.conn, player_id)
        await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v, order={"type": "build", **p})
        spend(v, p["cost"])
        site = v.state["slots"][order.slot]
        fields = len(game.content.pack["village"]["field_slots"])
        in_town = site.get("foreign") or fields <= order.slot < fields + int(game.content.pack["village"]["center_slots"])
        if p["level"] == 1 and in_town and not site.get("style"):
            site["style"] = await style_of(tx.conn, v, player["tribe"])
        # builders work in parallel; only further levels of the same site wait for the previous one
        start = max([game.clock.now(), *[j["due_at"] for j in jobs if j["payload"]["slot"] == order.slot]])
        await game.schedule(tx, BUILD, start + p["seconds"] * 1000, {**p, "started_at": start}, village_id=v.id)
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


class TrainOrder(BaseModel):
    unit: str
    count: int = Field(ge=1, le=100_000)


@router.post("/villages/{village_id}/train")
async def train(village_id: int, order: TrainOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        player = await get_player(tx.conn, player_id)
        p = plan(game.engine.plan_training, v.state, player["tribe"], order.unit, order.count)
        await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v, order={"type": "train", **p})
        spend(v, p["cost"])
        building = game.content.unit(order.unit)["building"]
        last = await tx.conn.fetchval(
            "SELECT max((payload->>'finishes_at')::bigint) FROM jobs WHERE village_id = $1 AND kind = $2 AND payload->>'building' = $3",
            v.id, TRAIN, building,
        )
        start = max(game.clock.now(), last or 0)
        each = p["seconds_each"] * 1000
        cost_each = {r: c / order.count for r, c in p["cost"].items()}
        payload = {"unit": order.unit, "building": building, "remaining": order.count, "each_ms": each,
                   "finishes_at": start + each * order.count, "cost_each": cost_each}
        await game.schedule(tx, TRAIN, start + each, payload, village_id=v.id)
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


class ResearchOrder(BaseModel):
    tech: str


@router.post("/villages/{village_id}/research")
async def research(village_id: int, order: ResearchOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Research a technology. Research runs one at a time per village, in order."""
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        jobs = await tx.conn.fetch("SELECT due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2", v.id, RESEARCH)
        queued = [j["payload"]["tech"] for j in jobs]
        p = plan(game.engine.plan_research, v.state, queued, order.tech)
        player = await get_player(tx.conn, player_id)
        await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v, order={"type": "research", **p})
        spend(v, p["cost"])
        start = max([game.clock.now(), *[j["due_at"] for j in jobs]])
        await game.schedule(tx, RESEARCH, start + p["seconds"] * 1000, {**p, "started_at": start}, village_id=v.id)
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


def demolish_rules(game: Game) -> dict[str, Any]:
    """``extensions.demolish``: ``refund`` (share of the build cost given back, 0.5) and
    ``keep`` (more buildings that cannot be pulled down). The growth building, great
    buildings and the wonder always stay."""
    cfg = game.content.extensions.get("demolish") or {}
    keep = set(cfg.get("keep", []))
    growth = (game.content.pack.get("village", {}).get("growth") or {}).get("building")
    if growth:
        keep.add(growth)
    keep.update(game.content.extensions.get("great_buildings", {}).get("buildings", []))
    keep.add((game.content.extensions.get("wonder") or {}).get("building", "wonder"))
    return {"refund": float(cfg.get("refund", 0.5)), "keep": keep}


def demolish_refund(game: Game, building: str, level: int, share: float) -> dict[str, float]:
    """``share`` of everything the levels 1..``level`` of ``building`` cost."""
    total: dict[str, float] = {}
    for lv in range(1, level + 1):
        for r, c in game.engine.build_cost(building, lv).items():
            total[r] = total.get(r, 0) + c
    return {r: float(int(c * share)) for r, c in total.items() if c * share >= 1}


@router.post("/villages/{village_id}/sites/{slot}/demolish")
async def demolish(village_id: int, slot: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Pull down the building on a center site at once, freeing the site and giving back
    part of what all its levels cost (``extensions.demolish.refund``, half by default)."""
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        await accrue(game, tx, v)
        cfg = demolish_rules(game)
        fields = len(game.content.pack["village"]["field_slots"])
        slots = v.state["slots"]
        if slot < 0 or slot >= len(slots):
            raise rule("invalid_slot")
        site = slots[slot]
        building, level = site.get("building"), int(site.get("level") or 0)
        if slot < fields or (slot >= fields + int(game.content.pack["village"]["center_slots"]) and not site.get("foreign")):
            raise rule("cannot_demolish_fields", "fields can only be upgraded")
        if not building or level <= 0:
            raise rule("nothing_to_demolish", "there is no building on this site")
        if building in cfg["keep"]:
            raise rule("cannot_demolish", "this building cannot be pulled down")
        jobs = await tx.conn.fetch(
            "SELECT kind, payload FROM jobs WHERE village_id = $1 AND kind = ANY($2::text[])", v.id, [BUILD, TRAIN, RESEARCH],
        )
        if any(j["kind"] == BUILD and j["payload"]["slot"] == slot for j in jobs):
            raise rule("site_busy", "cancel the construction on this site first")
        others = sum(1 for i, s in enumerate(slots) if i != slot and s.get("building") == building and (s.get("level") or 0) > 0)
        if not others:
            training = any(j["kind"] == TRAIN and j["payload"]["building"] == building for j in jobs)
            studying = any(
                j["kind"] == RESEARCH and (game.content.tech(j["payload"]["tech"]) or {}).get("building") == building for j in jobs
            )
            if training or studying:
                raise rule("building_in_use", "wait for the training or research in this building to finish, or cancel it")
        player = await get_player(tx.conn, player_id)
        await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v,
                        order={"type": "demolish", "slot": slot, "building": building, "level": level})
        back = demolish_refund(game, building, level, cfg["refund"])
        refund(game, v, back)  # into the storage as it stands, before a warehouse goes
        from .archaeology import bury

        bury(game, v, slot, site, "demolished", player_id)
        v.state["slots"][slot] = {"building": None, "level": 0} | ({"foreign": True} if site.get("foreign") else {})
        await save_village(game, tx, v)
        game.event(tx, v.player_id, "build.demolished", {"village_id": v.id, "slot": slot, "building": building, "level": level, "refund": back})
        await game.emit("ovian_build_demolished", game=game, tx=tx, village=v, building=building, level=level)
        return await push_village(game, tx, v)


@router.delete("/villages/{village_id}/jobs/{job_id}")
async def cancel(village_id: int, job_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Cancel a construction or training job and refund what has not been delivered."""
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        job = await tx.conn.fetchrow("SELECT * FROM jobs WHERE id = $1 AND village_id = $2 FOR UPDATE", job_id, v.id)
        if job is None or job["kind"] not in (BUILD, TRAIN, RESEARCH):
            raise not_found("job_not_found")
        p = job["payload"]
        if p.get("paid_by") and p["paid_by"] != player_id:
            raise rule("paid_by_overlord", "your overlord pays for this construction; only it can stop it")
        await accrue(game, tx, v)
        if job["kind"] == BUILD:
            later = await tx.conn.fetchval(
                "SELECT count(*) FROM jobs WHERE village_id = $1 AND kind = $2 AND (payload->>'slot')::int = $3 AND (payload->>'level')::int > $4",
                v.id, BUILD, p["slot"], p["level"],
            )
            if later:
                raise rule("cancel_later_first", "cancel the higher level queued on this slot first")
            refund(game, v, p["cost"])
            site = v.state["slots"][p["slot"]]
            if p["level"] == 1 and not site.get("level") and not site.get("foreign"):
                site.pop("style", None)  # never founded: the site forgets its style
        elif job["kind"] == RESEARCH:
            later = await tx.conn.fetch(
                "SELECT payload FROM jobs WHERE village_id = $1 AND kind = $2 AND due_at > $3", v.id, RESEARCH, job["due_at"],
            )
            needs = [x["payload"]["tech"] for x in later if p["tech"] in (game.content.tech(x["payload"]["tech"]) or {}).get("after", [])]
            if needs:
                raise rule("cancel_later_first", "cancel the research that builds on this one first")
            refund(game, v, p["cost"])
        else:
            refund(game, v, {r: c * p["remaining"] for r, c in p["cost_each"].items()})
        await tx.conn.execute("DELETE FROM jobs WHERE id = $1", job_id)
        await save_village(game, tx, v)
        return await push_village(game, tx, v)


# ---------------------------------------------------------------------- jobs


async def on_build_complete(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    v = await own_or_none(tx, job["village_id"])
    if v is None:
        return
    await accrue(game, tx, v, at=job["due_at"])
    p = job["payload"]
    v.state = game.engine.complete_build(v.state, p["slot"], p["building"], p["level"])
    if p["level"] == 1:
        from .archaeology import founded

        founded(game, v, p["slot"], p.get("paid_by") or v.player_id)
    await save_village(game, tx, v)
    game.event(tx, v.player_id, "build.completed", {"village_id": v.id, "slot": p["slot"], "building": p["building"], "level": p["level"]})
    await game.emit("ovian_build_completed", game=game, tx=tx, village=v, building=p["building"], level=p["level"])
    await push_village(game, tx, v)


async def on_train_unit(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    v = await own_or_none(tx, job["village_id"])
    if v is None:
        return
    p = dict(job["payload"])
    await accrue(game, tx, v, at=job["due_at"])
    late = max(0, game.clock.now() - job["due_at"])
    ready = min(p["remaining"], 1 + late // p["each_ms"])
    units = v.state.setdefault("units", {})
    units[p["unit"]] = units.get(p["unit"], 0) + ready
    p["remaining"] -= ready
    if p["remaining"] > 0:
        await game.schedule(tx, TRAIN, job["due_at"] + ready * p["each_ms"], p, village_id=v.id)
    await save_village(game, tx, v)
    game.event(tx, v.player_id, "train.completed", {"village_id": v.id, "unit": p["unit"], "count": ready, "remaining": p["remaining"]})
    await push_village(game, tx, v)


async def on_research_complete(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    v = await own_or_none(tx, job["village_id"])
    if v is None:
        return
    await accrue(game, tx, v, at=job["due_at"])
    tech = job["payload"]["tech"]
    v.state = game.engine.complete_research(v.state, tech)
    await save_village(game, tx, v)
    game.event(tx, v.player_id, "research.completed", {"village_id": v.id, "tech": tech})
    await push_village(game, tx, v)


async def own_or_none(tx: Tx, village_id: int | None) -> VillageRow | None:
    from ..repo import lock_villages

    if village_id is None:
        return None
    return (await lock_villages(tx.conn, village_id)).get(village_id)


module = Module("villages", router=router, jobs={BUILD: on_build_complete, TRAIN: on_train_unit, RESEARCH: on_research_complete})
