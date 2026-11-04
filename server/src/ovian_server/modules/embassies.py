"""Embassies: the foreign quarter an overlord opens in a vassal city.

When a city submits to a player who never ruled it before, it gets new sites at the end of its
site list (``foreign`` slots): one for the overlord's ``building`` (the embassy) and
``exchange_slots`` free ones for other foreign buildings (``foreign: true`` in the pack; the
foreign exchange). They are built in the style of the overlord's civilization.

- **The embassy** is built and paid for by the overlord only (``POST /villages/{id}/embassy``
  with ``from``, the overlord's city that pays). Its level adds whatever effects the pack gives it
  (antiquity: contentment). The vassal cannot build, cancel or pull it down.
- **The foreign exchange** is the vassal's own: every level lowers the tribute it pays by
  ``exchange_relief`` (a fraction of the tribute, at most all of it).
- **Breaking free** (or passing to another overlord) leaves the embassy as ``ruin``, in the
  old overlord's style. An embassy never started just leaves an empty foreign site. A ruin can be
  pulled down to free its site. If the same player rules the city again, the old embassy site is
  reused instead of opening a new quarter.

Architecture: every site remembers the civilization it was founded under (``style`` on the slot):
the overlord's for a vassal, the owner's otherwise. Buildings never change style when the city
changes hands, so a city may show a mix of styles. The village view lists the foreign quarters
under ``foreign`` and, for an overlord, the embassy of each vassal under ``vassals[].embassy``.

    extensions:
      embassies: { building: embassy, ruin: ruin, exchange: exchange, exchange_slots: 1, exchange_relief: 0.03 }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from ovian_engine import PlanError
from pydantic import BaseModel, ConfigDict, Field

from ..deps import GameDep
from ..errors import rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, get_village, lock_villages, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

router = APIRouter(tags=["submission"])
DEFAULTS: dict[str, Any] = {"building": "embassy", "ruin": "ruin", "exchange": "exchange", "exchange_slots": 1, "exchange_relief": 0.03,
                            "overlord": [], "overlord_slots": 0}


def cfg(game: Game) -> dict[str, Any] | None:
    c = game.content.extensions.get("embassies")
    return None if c is None else DEFAULTS | c


def overlord_buildings(c: dict[str, Any]) -> set[str]:
    return {c["building"], *c["overlord"]}


def tribute_factor(game: Game, v: VillageRow) -> float:
    """What is left of the tribute after the city's foreign exchanges."""
    c = cfg(game)
    if c is None:
        return 1.0
    levels = sum(int(s.get("level") or 0) for s in v.state["slots"] if s.get("building") == c["exchange"])
    return max(0.0, 1.0 - levels * float(c["exchange_relief"]))


def quarters(v: VillageRow) -> list[dict[str, Any]]:
    return v.meta.setdefault("foreign", [])


def quarter_of(v: VillageRow, player_id: int | None, village_id: int | None = None) -> dict[str, Any] | None:
    return next((q for q in quarters(v) if q["player_id"] == player_id or (village_id and q.get("village_id") == village_id)), None)


def lord_slots(q: dict[str, Any]) -> list[int]:
    """The sites only this quarter's overlord may build on: its embassy and its overlord sites."""
    return [q["embassy"], *q.get("lord_sites", [])]


def reserved(v: VillageRow) -> dict[int, dict[str, Any]]:
    """Every overlord site of the city, past overlords' included: its owner may never build there."""
    return {i: q for q in v.meta.get("foreign", []) for i in lord_slots(q)}


async def site_jobs(conn: asyncpg.Connection, village_id: int, slot: int) -> list[asyncpg.Record]:
    from .villages import BUILD

    return await conn.fetch(
        "SELECT id, due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2 AND (payload->>'slot')::int = $3 ORDER BY due_at",
        village_id, BUILD, slot,
    )


embassy_jobs = site_jobs


async def sync_culture(game: Game, tx: Tx, lord_id: int | None) -> None:
    """Set an overlord city's culture income to what its vassals' cultural exchanges send it."""
    if not lord_id:
        return
    rows = await tx.conn.fetch("SELECT v.state FROM vassals s JOIN villages v ON v.id = s.vassal_id WHERE s.overlord_id = $1", lord_id)
    total = sum(float(game.engine.economy(r["state"]).get("culture_out", 0.0)) for r in rows)
    lord = (await lock_villages(tx.conn, lord_id)).get(lord_id)
    if lord is None or abs(float(lord.state.get("culture_in", 0.0)) - total) < 1e-6:
        return
    await accrue(game, tx, lord)
    if total:
        lord.state["culture_in"] = round(total, 3)
    else:
        lord.state.pop("culture_in", None)
    await save_village(game, tx, lord)


# --------------------------------------------------------------------- hooks


def _open_sites(c: dict[str, Any], q: dict[str, Any], slots: list[dict[str, Any]], tribe: str) -> None:
    if "lord_sites" not in q:
        q["lord_sites"] = []
        for _ in range(int(c["overlord_slots"])):
            q["lord_sites"].append(len(slots))
            slots.append({"building": None, "level": 0, "style": tribe, "foreign": True})


@hookimpl
async def ovian_vassal_bound(game: Game, tx: Tx, vassal: VillageRow, lord: VillageRow) -> None:
    c = cfg(game)
    if c is None:
        return
    tribe = await tx.conn.fetchval("SELECT tribe FROM players WHERE id = $1", lord.player_id)
    vassal.state = game.engine.normalize(vassal.state)
    slots = vassal.state["slots"]
    q = quarter_of(vassal, lord.player_id)
    embassy = {"building": c["building"], "level": 0, "style": tribe, "foreign": True}
    if q is not None:  # an old ruler returns: its old embassy site is rebuilt from the ground, its ruins cleared
        if slots[q["embassy"]].get("building") in (None, c["ruin"]):
            slots[q["embassy"]] = embassy
        for i in q.get("lord_sites", []):
            if slots[i].get("building") == c["ruin"]:
                slots[i] = {"building": None, "level": 0, "style": tribe, "foreign": True}
        q["village_id"] = lord.id
        q.pop("until", None)
        _open_sites(c, q, slots, tribe)
    else:
        q = {"player_id": lord.player_id, "village_id": lord.id, "tribe": tribe, "since": game.clock.now(), "embassy": len(slots)}
        slots.append(embassy)
        _open_sites(c, q, slots, tribe)
        q["sites"] = []
        for _ in range(int(c["exchange_slots"])):
            q["sites"].append(len(slots))
            slots.append({"building": None, "level": 0, "style": tribe, "foreign": True})
        quarters(vassal).append(q)
    await save_village(game, tx, vassal)


@hookimpl
async def ovian_started(game: Game) -> None:
    """Vassals that submitted before embassies (or overlord sites) existed get them now."""
    c = cfg(game)
    if c is None:
        return
    async with game.tx() as tx:
        rows = await tx.conn.fetch(
            """SELECT s.vassal_id, s.overlord_id FROM vassals s JOIN villages v ON v.id = s.vassal_id JOIN villages o ON o.id = s.overlord_id
               WHERE v.player_id <> o.player_id ORDER BY s.vassal_id""")
        for r in rows:
            got = await lock_villages(tx.conn, r["vassal_id"], r["overlord_id"])
            vassal, lord = got.get(r["vassal_id"]), got.get(r["overlord_id"])
            if vassal is None or lord is None:
                continue
            q = quarter_of(vassal, lord.player_id)
            if q is None or ("lord_sites" not in q and c["overlord_slots"]):
                await accrue(game, tx, vassal)
                await ovian_vassal_bound(game, tx, vassal, lord)


@hookimpl
async def ovian_vassal_released(game: Game, tx: Tx, vassal: VillageRow, lord_id: int, lord_player_id: int | None, reason: str) -> None:
    c = cfg(game)
    if c is None:
        return
    q = quarter_of(vassal, lord_player_id, lord_id)
    if q is None:
        return
    slots = vassal.state["slots"]
    from .villages import refund

    for i in lord_slots(q):
        if i >= len(slots):
            continue
        # unfinished levels are dropped; the overlord gets back what it paid for them
        for j in await site_jobs(tx.conn, vassal.id, i):
            p = j["payload"]
            await tx.conn.execute("DELETE FROM jobs WHERE id = $1", j["id"])
            payer = (await lock_villages(tx.conn, p["paid_from"])).get(p["paid_from"]) if p.get("paid_from") else None
            if payer:
                await accrue(game, tx, payer)
                refund(game, payer, p["cost"])
                await save_village(game, tx, payer)
        s = slots[i]
        style = s.get("style") or q["tribe"]
        if s.get("building") in overlord_buildings(c) and int(s.get("level") or 0) > 0:
            from .archaeology import bury

            bury(game, vassal, i, s, "ruined", lord_player_id)
            slots[i] = {"building": c["ruin"], "level": 1, "style": style, "foreign": True}
        elif s.get("building") != c["ruin"]:
            slots[i] = {"building": None, "level": 0, "style": style, "foreign": True}
    q["until"] = game.clock.now()
    await save_village(game, tx, vassal)
    await sync_culture(game, tx, lord_id)  # the cultural exchange is gone


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    c = cfg(game)
    if c is None:
        return
    b = order.get("building")
    if order.get("type") == "build":
        if order.get("slot") in reserved(village):
            raise rule("overlord_site", "only an overlord builds on this site")
        if b in overlord_buildings(c):
            raise rule("embassy_overlord_only", "only the overlord raises this building, and pays for it")
        if b == c["ruin"]:
            raise rule("cannot_build_ruin", "a ruin cannot be built")
    elif order.get("type") == "demolish" and b in overlord_buildings(c):
        raise rule("cannot_demolish", "it stands as long as its overlord rules the city")


async def _exchange_changed(game: Game, tx: Tx, village: VillageRow, building: str) -> None:
    c = cfg(game)
    if c is None:
        return
    if building == c["exchange"]:
        from .submission import apply_tax

        await apply_tax(game, tx, village)  # the exchange lightens the tribute
    if village.state.get("tribute"):
        lord = await tx.conn.fetchval("SELECT overlord_id FROM vassals WHERE vassal_id = $1", village.id)
        if lord and (building in c["overlord"] or game.engine.economy(village.state).get("culture_out")):
            await sync_culture(game, tx, lord)  # what the cultural exchange sends changes with the city's culture


@hookimpl
async def ovian_build_completed(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    await _exchange_changed(game, tx, village, building)


@hookimpl
async def ovian_build_demolished(game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
    await _exchange_changed(game, tx, village, building)


async def site_info(conn: asyncpg.Connection, v: VillageRow, slot: int) -> dict[str, Any]:
    s = v.state["slots"][slot]
    jobs = await site_jobs(conn, v.id, slot)
    return {"slot": slot, "building": s.get("building") or (jobs[0]["payload"]["building"] if jobs else None), "level": int(s.get("level") or 0),
            "queued": [{"level": j["payload"]["level"], "due_at": j["due_at"]} for j in jobs], "style": s.get("style")}


async def embassy_info(game: Game, conn: asyncpg.Connection, v: VillageRow, player_id: int) -> dict[str, Any] | None:
    q = quarter_of(v, player_id)
    if q is None or q["embassy"] >= len(v.state["slots"]):
        return None
    return await site_info(conn, v, q["embassy"])


async def lord_sites_info(game: Game, conn: asyncpg.Connection, v: VillageRow, player_id: int) -> list[dict[str, Any]]:
    q = quarter_of(v, player_id)
    if q is None:
        return []
    return [await site_info(conn, v, i) for i in q.get("lord_sites", []) if i < len(v.state["slots"])]


async def garrison_room(game: Game, conn: asyncpg.Connection, host: VillageRow, player_id: int) -> tuple[int, int]:
    """(capacity, troops of this player already out on campaigns from the garrison in ``host``)."""
    lord = await conn.fetchval(
        "SELECT o.player_id FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE s.vassal_id = $1", host.id)
    if lord != player_id:
        return 0, 0
    cap = int(game.engine.economy(host.state).get("garrison", 0))
    rows = await conn.fetch(
        """SELECT units FROM movements WHERE player_id = $1
           AND ((from_id = $2 AND kind <> 'return' AND home_id <> $2) OR (to_id = $2 AND kind = 'return' AND home_id <> $2))""",
        player_id, host.id)
    return cap, sum(int(n) for r in rows for n in r["units"].values())


@hookimpl(trylast=True)
async def ovian_village_view(game: Game, conn: asyncpg.Connection, village: VillageRow, view: dict[str, Any]) -> None:
    c = cfg(game)
    if c is None:
        return
    if village.meta.get("foreign"):
        view["foreign"] = [{k: q.get(k) for k in ("player_id", "tribe", "since", "until", "embassy", "lord_sites", "sites")} for q in village.meta["foreign"]]
    if village.state.get("tribute") and not village.meta.get("mother_id"):
        f = tribute_factor(game, village)
        if f < 1:
            view["exchange_relief"] = round(1 - f, 4)
    for x in view.get("vassals") or []:
        if x.get("colony"):
            continue
        vv = await get_village(conn, x["village"]["id"])
        x["embassy"] = await embassy_info(game, conn, vv, village.player_id)
        x["sites"] = await lord_sites_info(game, conn, vv, village.player_id)
        cap, out = await garrison_room(game, conn, vv, village.player_id)
        if cap:
            here = await conn.fetchval("SELECT units FROM stationed WHERE host_id = $1 AND home_id = $2", vv.id, village.id) or {}
            x["garrison"] = {"capacity": cap, "out": out, "here": here}
            from .auxiliaries import garrison_view

            aux = await garrison_view(game, conn, vv, village.player_id)
            if aux:
                x["garrison"]["auxiliaries"] = aux


# -------------------------------------------------------------------- orders


class SiteOrder(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    #: The overlord's city that pays.
    from_: int = Field(alias="from")
    #: What to raise on an empty overlord site (cultural_exchange, garrison); upgrades need none.
    building: str | None = None


@router.post("/villages/{vassal_id}/foreign/{slot}")
async def build_overlord_site(vassal_id: int, slot: int, order: SiteOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Raise a building on one of your overlord sites in a vassal city (the embassy, a cultural exchange, a garrison)
    by one level, paid by one of your own cities (``from``)."""
    return await _build_site(game, player_id, vassal_id, slot, order.from_, order.building)


@router.post("/villages/{vassal_id}/embassy")
async def build_embassy(vassal_id: int, order: SiteOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Raise the embassy in a vassal city one level, paid by one of the overlord's cities (``from``)."""
    return await _build_site(game, player_id, vassal_id, None, order.from_, None)


async def _build_site(game: Game, player_id: int, vassal_id: int, slot: int | None, payer_id: int, building: str | None) -> dict[str, Any]:
    from .submission import overlord_of
    from .villages import BUILD, push_village, spend

    c = cfg(game)
    if c is None:
        raise rule("no_embassies", "this world has no embassies")
    async with game.tx() as tx:
        rows = await lock_villages(tx.conn, vassal_id, payer_id)
        vassal, payer = rows.get(vassal_id), rows.get(payer_id)
        if vassal is None or payer is None:
            raise rule("village_not_found")
        if payer.player_id != player_id:
            raise rule("not_your_village", "pay from one of your own cities")
        lord = await overlord_of(tx.conn, vassal.id)
        if lord is None or lord["player_id"] != player_id or vassal.player_id == player_id:
            raise rule("not_your_vassal", "only the overlord of this city can build there")
        q = quarter_of(vassal, player_id)
        if q is None:
            raise rule("no_embassy_site", "this city has no site for you")
        slot = q["embassy"] if slot is None else slot
        if slot not in lord_slots(q):
            raise rule("not_your_site", "this is not one of your sites in that city")
        site = vassal.state["slots"][slot]
        if slot == q["embassy"]:
            building = c["building"]
        elif site.get("building"):
            building = site["building"]
        elif building not in c["overlord"]:
            raise rule("not_overlord_building", "build one of: " + ", ".join(c["overlord"]))
        await accrue(game, tx, vassal)
        await accrue(game, tx, payer)
        jobs = await site_jobs(tx.conn, vassal.id, slot)
        queue = [{"slot": j["payload"]["slot"], "building": j["payload"]["building"], "level": j["payload"]["level"]} for j in jobs]
        # the vassal's site and builders, the overlord's purse
        state = dict(vassal.state) | {"resources": payer.state["resources"]}
        try:
            p = game.engine.plan_build(state, queue, slot, building)
        except PlanError as e:
            raise rule(str(e.args[0])) from None
        spend(payer, p["cost"])
        start = max([game.clock.now(), *[j["due_at"] for j in jobs]])
        await game.schedule(tx, BUILD, start + p["seconds"] * 1000,
                            {**p, "started_at": start, "paid_by": player_id, "paid_from": payer.id}, village_id=vassal.id)
        await save_village(game, tx, payer)
        await push_village(game, tx, vassal)
        out = await push_village(game, tx, payer)
        return out | {"embassy": await embassy_info(game, tx.conn, vassal, player_id), "site": await site_info(tx.conn, vassal, slot)}


module = Module("embassies", router=router)
