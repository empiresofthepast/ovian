"""Auxiliaries: an overlord levies the vassal's own troops in its garrison.

With a garrison in a vassal city, the overlord may train that city's units there (its civilization's,
in its buildings, with its techs), paid by one of the overlord's own cities at ``cost`` times the usual
price. They are stationed in the garrison as the overlord's troops (fed by the host, like any troops
stationed there) and set out from it like the rest of the garrison. Levied plus queued auxiliaries
never exceed the garrison's room.

Levies anger the city: every 100 cost ``mood_per_100`` contentment for ``mood_hours`` (at world
speed), ``mood_max`` at most per levy.

When the city breaks free, its auxiliaries go home to their own people: those in the garrison join
the freed city's army; levies still in training are dropped and their price goes back to the payer.

    extensions:
      auxiliaries: { cost: 1.25, mood_per_100: -3, mood_max: -15, mood_hours: 24 }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter
from ovian_engine import PlanError
from pydantic import BaseModel, ConfigDict, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, lock_villages, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

AUX = "aux.train"
router = APIRouter(tags=["submission"])


def cfg(game: Game) -> dict[str, Any] | None:
    c = game.content.extensions.get("auxiliaries")
    if c is None or not game.content.extensions.get("embassies"):
        return None
    return {"cost": 1.25, "mood_per_100": -3.0, "mood_max": -15.0, "mood_hours": 24.0} | c


async def _tribe(conn: asyncpg.Connection, player_id: int) -> str:
    return await conn.fetchval("SELECT tribe FROM players WHERE id = $1", player_id)


async def _jobs(conn: asyncpg.Connection, vassal_id: int) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT id, due_at, payload FROM jobs WHERE village_id = $1 AND kind = $2 ORDER BY due_at, id", vassal_id, AUX)


async def levied(game: Game, conn: asyncpg.Connection, vassal: VillageRow, lord_player: int) -> tuple[int, int]:
    """(auxiliaries of ``lord_player`` stationed in ``vassal`` or out on campaign from it, in training there)."""
    tribe = await _tribe(conn, vassal.player_id)
    mine = {u["id"] for u in game.content.pack["units"] if u.get("tribe") == tribe}
    rows = await conn.fetch(
        """SELECT s.units FROM stationed s JOIN villages h ON h.id = s.home_id WHERE s.host_id = $1 AND h.player_id = $2
           UNION ALL
           SELECT m.units FROM movements m WHERE m.player_id = $2 AND m.home_id <> $1
             AND ((m.from_id = $1 AND m.kind <> 'return') OR (m.to_id = $1 AND m.kind = 'return'))""",
        vassal.id, lord_player)
    here = sum(int(n) for r in rows for u, n in r["units"].items() if u in mine)
    queued = sum(int(j["payload"]["remaining"]) for j in await _jobs(conn, vassal.id) if j["payload"].get("player_id") == lord_player)
    return here, queued


async def levy_options(game: Game, conn: asyncpg.Connection, vassal: VillageRow) -> list[dict[str, Any]]:
    """The vassal's units its buildings and techs can train (for the overlord's levy)."""
    tribe = await _tribe(conn, vassal.player_id)
    c = cfg(game) or {}
    out = []
    rich = {**vassal.state, "resources": {r["id"]: 1e12 for r in game.content.pack["resources"]}}
    for u in game.content.pack["units"]:
        if u.get("tribe") != tribe:
            continue
        try:
            p = game.engine.plan_training(rich, tribe, u["id"], 1)
        except PlanError:
            continue
        out.append({"unit": u["id"], "name": u.get("name", u["id"]), "seconds_each": p["seconds_each"],
                    "cost_each": {r: round(n * float(c.get("cost", 1.25))) for r, n in p["cost"].items()}})
    return out


class LevyOrder(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    #: The overlord's city that pays.
    from_: int = Field(alias="from")
    unit: str
    count: int = Field(ge=1, le=100_000)


@router.post("/villages/{vassal_id}/auxiliaries")
async def levy(vassal_id: int, order: LevyOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Train ``count`` of the vassal's ``unit`` in its garrison, paid by your city ``from``."""
    from .contentment import add_effect, schedule_end
    from .embassies import garrison_room
    from .submission import overlord_of
    from .villages import push_village, spend

    c = cfg(game)
    if c is None:
        raise rule("no_auxiliaries", "this world has no auxiliaries")
    async with game.tx() as tx:
        got = await lock_villages(tx.conn, vassal_id, order.from_)
        vassal, payer = got.get(vassal_id), got.get(order.from_)
        if vassal is None or payer is None or payer.player_id != player_id:
            raise not_found("village_not_found")
        lord = await overlord_of(tx.conn, vassal.id)
        if lord is None or lord["player_id"] != player_id or vassal.player_id == player_id:
            raise rule("not_your_vassal", "you can only levy troops in your vassals' cities")
        cap, _ = await garrison_room(game, tx.conn, vassal, player_id)
        if cap <= 0:
            raise rule("no_garrison", "build a garrison in that city first")
        here, queued = await levied(game, tx.conn, vassal, player_id)
        if here + queued + order.count > cap:
            raise rule("garrison_full", f"the garrison has room for {cap} auxiliaries ({here + queued} levied or in training)")
        await accrue(game, tx, payer)
        tribe = await _tribe(tx.conn, vassal.player_id)
        try:
            p = game.engine.plan_training({**vassal.state, "resources": {r["id"]: 1e12 for r in game.content.pack["resources"]}},
                                          tribe, order.unit, order.count)
        except PlanError as e:
            raise rule(str(e), "the city cannot train these troops") from e
        cost = {r: float(round(n * float(c["cost"]))) for r, n in p["cost"].items()}
        if not all(payer.state["resources"].get(r, 0) >= n for r, n in cost.items()):
            raise rule("insufficient_resources")
        spend(payer, cost)
        last = max([game.clock.now(), *[int(j["payload"]["finishes_at"]) for j in await _jobs(tx.conn, vassal.id)]])
        each = int(p["seconds_each"]) * 1000
        payload = {"unit": order.unit, "remaining": order.count, "each_ms": each, "finishes_at": last + each * order.count,
                   "cost_each": {r: n / order.count for r, n in cost.items()}, "player_id": player_id, "home_id": lord["id"],
                   "paid_from": payer.id, "count": order.count}
        await game.schedule(tx, AUX, last + each, payload, village_id=vassal.id)
        await save_village(game, tx, payer)
        # the levy angers the city
        await accrue(game, tx, vassal)
        mood = max(float(c["mood_max"]), float(c["mood_per_100"]) * order.count / 100)
        if mood:
            until = add_effect(game, vassal.meta, "contentment", "Levies for the overlord", round(mood, 1), float(c["mood_hours"]))
            await schedule_end(game, tx, until, village_id=vassal.id)
        await save_village(game, tx, vassal)
        game.event(tx, vassal.player_id, "auxiliaries.levied", {"village_id": vassal.id, "unit": order.unit, "count": order.count})
        await push_village(game, tx, vassal)
        return await push_village(game, tx, (await lock_villages(tx.conn, lord["id"]))[lord["id"]])


async def on_trained(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    p = dict(job["payload"])
    got = await lock_villages(tx.conn, job["village_id"], p["home_id"])
    vassal, home = got.get(job["village_id"]), got.get(p["home_id"])
    if vassal is None or home is None:
        return
    late = max(0, game.clock.now() - job["due_at"])
    ready = min(int(p["remaining"]), 1 + late // int(p["each_ms"]))
    await accrue(game, tx, vassal)  # it feeds them from now on
    s = await tx.conn.fetchrow("SELECT id, units FROM stationed WHERE host_id = $1 AND home_id = $2 FOR UPDATE", vassal.id, home.id)
    if s is None:
        await tx.conn.execute("INSERT INTO stationed(host_id, home_id, units) VALUES ($1, $2, $3)", vassal.id, home.id, {p["unit"]: ready})
    else:
        units = dict(s["units"])
        units[p["unit"]] = int(units.get(p["unit"], 0)) + ready
        await tx.conn.execute("UPDATE stationed SET units = $2 WHERE id = $1", s["id"], units)
    p["remaining"] = int(p["remaining"]) - ready
    if p["remaining"] > 0:
        await game.schedule(tx, AUX, job["due_at"] + ready * int(p["each_ms"]), p, village_id=vassal.id)
    await save_village(game, tx, vassal)
    game.event(tx, home.player_id, "auxiliaries.trained", {"village_id": vassal.id, "unit": p["unit"], "count": ready, "remaining": p["remaining"]})
    await push_village(game, tx, home)


@router.delete("/villages/{vassal_id}/auxiliaries/{job_id}")
async def cancel(vassal_id: int, job_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Stop a levy: what has not been trained is paid back to the city that paid."""
    from .villages import push_village

    async with game.tx() as tx:
        job = await tx.conn.fetchrow("SELECT * FROM jobs WHERE id = $1 AND village_id = $2 AND kind = $3 FOR UPDATE", job_id, vassal_id, AUX)
        if job is None or job["payload"].get("player_id") != player_id:
            raise not_found("job_not_found")
        payer = await _refund(game, tx, job)
        return await push_village(game, tx, payer) if payer else {}


async def _refund(game: Game, tx: Tx, job: asyncpg.Record) -> VillageRow | None:
    from .villages import refund

    p = job["payload"]
    await tx.conn.execute("DELETE FROM jobs WHERE id = $1", job["id"])
    payer = (await lock_villages(tx.conn, p["paid_from"])).get(p["paid_from"])
    if payer is None:
        return None
    await accrue(game, tx, payer)
    refund(game, payer, {r: n * int(p["remaining"]) for r, n in p["cost_each"].items()})
    await save_village(game, tx, payer)
    return payer


@hookimpl
async def ovian_vassal_released(game: Game, tx: Tx, vassal: VillageRow, lord_id: int, lord_player_id: int | None, reason: str) -> None:
    """The auxiliaries go home to their people: they join the freed city's army."""
    if cfg(game) is None or lord_player_id is None:
        return
    for j in await _jobs(tx.conn, vassal.id):
        if j["payload"].get("player_id") == lord_player_id:
            await _refund(game, tx, j)
    tribe = await _tribe(tx.conn, vassal.player_id)
    mine = {u["id"] for u in game.content.pack["units"] if u.get("tribe") == tribe}
    rows = await tx.conn.fetch(
        "SELECT s.id, s.units FROM stationed s JOIN villages h ON h.id = s.home_id WHERE s.host_id = $1 AND h.player_id = $2 FOR UPDATE",
        vassal.id, lord_player_id)
    back: dict[str, int] = {}
    for r in rows:
        units = dict(r["units"])
        for u in [u for u in units if u in mine]:
            back[u] = back.get(u, 0) + int(units.pop(u))
        if units:
            await tx.conn.execute("UPDATE stationed SET units = $2 WHERE id = $1", r["id"], units)
        else:
            await tx.conn.execute("DELETE FROM stationed WHERE id = $1", r["id"])
    if not back:
        return
    await accrue(game, tx, vassal)
    own = vassal.state.setdefault("units", {})
    for u, n in back.items():
        own[u] = int(own.get(u, 0)) + n
    await save_village(game, tx, vassal)
    total = sum(back.values())
    data = {"village": vassal.public(), "units": back}
    await add_report(game, tx, vassal.player_id, "auxiliaries", f"{total} auxiliaries come home to {vassal.name}", data)
    await add_report(game, tx, lord_player_id, "auxiliaries", f"{total} auxiliaries desert to {vassal.name}", data)


async def garrison_view(game: Game, conn: asyncpg.Connection, vassal: VillageRow, lord_player: int) -> dict[str, Any] | None:
    """For an overlord's view of a vassal with a garrison: what it can levy, and the levies in training."""
    if cfg(game) is None:
        return None
    here, queued = await levied(game, conn, vassal, lord_player)
    return {"levied": here, "queued": queued, "options": await levy_options(game, conn, vassal),
            "training": [{"id": j["id"], "unit": j["payload"]["unit"], "remaining": j["payload"]["remaining"],
                          "next_at": j["due_at"], "finishes_at": j["payload"]["finishes_at"]}
                         for j in await _jobs(conn, vassal.id) if j["payload"].get("player_id") == lord_player]}


module = Module("auxiliaries", router=router, jobs={AUX: on_trained})
