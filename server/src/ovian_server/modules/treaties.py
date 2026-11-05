"""Treaties between players: pacts of peace, with an optional tribute.

``extensions.treaties``::

    treaties:
      notice_hours: 6        # real hours a pact still holds after one side ends it
      treachery_hours: 48    # real hours an oath-breaker is marked on the map
      treachery_mood: -15    # contentment in every city of the oath-breaker meanwhile
      min_tribute_hours: 1   # a tribute is paid at most this often (real hours)

- ``POST /treaties`` proposes a pact to a player (``to``: their name), optionally with a tribute:
  ``{"payer": "me" | "them", "resources": {...}, "every_hours": 12}``.
- ``POST /treaties/{id}/accept`` (the other side) seals it; ``DELETE /treaties/{id}`` withdraws or
  declines a proposal, or gives notice on a pact: it holds ``notice_hours`` more, then ends.
- The tribute goes from the payer's first city straight to the other side's first city, every
  ``every_hours``. When the payer cannot pay, the pact lapses (no dishonour).
- A pact does not stop an attack: attacking or raiding a pact partner breaks it. The oath-breaker
  is marked ``treacherous`` on the map and in profiles for ``treachery_hours``, and their cities
  grumble (``treachery_mood``). The chronicle tells the world.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..hooks import hookimpl
from ..repo import VillageRow, accrue, add_report, get_village, save_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

TRIBUTE = "treaty.tribute"
END = "treaty.end"
router = APIRouter(tags=["treaties"])


def cfg(game: Game) -> dict[str, float]:
    c = game.content.extensions.get("treaties") or {}
    d = {"notice_hours": 6, "treachery_hours": 48, "treachery_mood": -15, "min_tribute_hours": 1}
    return {k: float(c.get(k, v)) for k, v in d.items()}


async def _names(conn: asyncpg.Connection, *ids: int) -> dict[int, str]:
    return {r["id"]: r["username"] for r in await conn.fetch("SELECT id, username FROM players WHERE id = ANY($1::bigint[])", list(ids))}


def view(t: asyncpg.Record | dict[str, Any], me: int, names: dict[int, str]) -> dict[str, Any]:
    other = t["b_id"] if t["a_id"] == me else t["a_id"]
    trib = t["tribute"]
    return {"id": t["id"], "status": t["status"], "with": {"id": other, "name": names.get(other, "?")}, "proposed_by_me": t["a_id"] == me,
            "since": t["since"], "ends_at": t["ends_at"], "last_paid_at": t["last_paid_at"], "created_at": t["created_at"],
            "tribute": None if not trib else {"i_pay": trib["payer"] == me, "resources": trib["resources"], "every_hours": trib["every_ms"] / 3_600_000}}


async def pact_between(conn: asyncpg.Connection, a: int, b: int) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM treaties WHERE least(a_id, b_id) = least($1::bigint, $2::bigint) AND greatest(a_id, b_id) = greatest($1::bigint, $2::bigint)", a, b)


async def first_city(conn: asyncpg.Connection, player_id: int) -> VillageRow | None:
    vid = await conn.fetchval("SELECT id FROM villages WHERE player_id = $1 ORDER BY id LIMIT 1", player_id)
    return await get_village(conn, vid, lock=True) if vid else None


@router.get("/treaties")
async def my_treaties(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Your treaties (proposed and active), and until when you are marked as an oath-breaker."""
    async with game.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM treaties WHERE a_id = $1 OR b_id = $1 ORDER BY id", player_id)
        names = await _names(conn, *{r["a_id"] for r in rows}, *{r["b_id"] for r in rows})
        meta = await conn.fetchval("SELECT meta FROM players WHERE id = $1", player_id) or {}
    return {"treaties": [view(r, player_id, names) for r in rows], "treacherous_until": meta.get("treacherous_until"), "rules": cfg(game)}


class Tribute(BaseModel):
    payer: Literal["me", "them"]
    resources: dict[str, float]
    every_hours: float = Field(gt=0)


class Proposal(BaseModel):
    to: str
    tribute: Tribute | None = None


@router.post("/treaties", status_code=201)
async def propose(body: Proposal, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Offer a pact of peace to a player, with an optional tribute."""
    from .market import clean

    async with game.tx() as tx:
        other = await tx.conn.fetchrow("SELECT id, npc FROM players WHERE lower(username) = lower($1)", body.to)
        if other is None or other["npc"]:
            raise not_found("player_not_found")
        if other["id"] == player_id:
            raise rule("own_treaty", "a pact needs someone else")
        if await pact_between(tx.conn, player_id, other["id"]):
            raise rule("treaty_exists", "there is already a pact or a proposal between you")
        tribute = None
        if body.tribute:
            if body.tribute.every_hours < cfg(game)["min_tribute_hours"]:
                raise rule("tribute_too_often", f"at most once every {cfg(game)['min_tribute_hours']:g} hours")
            tribute = {"payer": player_id if body.tribute.payer == "me" else other["id"], "resources": clean(body.tribute.resources, game),
                       "every_ms": int(body.tribute.every_hours * 3_600_000)}
        now = game.clock.now()
        t = await tx.conn.fetchrow("INSERT INTO treaties(a_id, b_id, status, tribute, created_at) VALUES ($1, $2, 'proposed', $3, $4) RETURNING *",
                                   player_id, other["id"], tribute, now)
        names = await _names(tx.conn, player_id, other["id"])
        await add_report(game, tx, other["id"], "treaty", f"{names[player_id]} offers you a pact", view(t, other["id"], names))
        game.event(tx, other["id"], "treaty.proposed", view(t, other["id"], names))
        return view(t, player_id, names)


@router.post("/treaties/{treaty_id}/accept")
async def accept(treaty_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    from .chronicle import record

    async with game.tx() as tx:
        t = await tx.conn.fetchrow("SELECT * FROM treaties WHERE id = $1 FOR UPDATE", treaty_id)
        if t is None or player_id not in (t["a_id"], t["b_id"]):
            raise not_found("treaty_not_found")
        if t["status"] != "proposed" or t["b_id"] != player_id:
            raise rule("not_yours_to_accept")
        now = game.clock.now()
        t = await tx.conn.fetchrow("UPDATE treaties SET status = 'active', since = $2 WHERE id = $1 RETURNING *", treaty_id, now)
        if t["tribute"]:
            await game.schedule(tx, TRIBUTE, now + int(t["tribute"]["every_ms"]), {"treaty": t["id"]})
        names = await _names(tx.conn, t["a_id"], t["b_id"])
        await add_report(game, tx, t["a_id"], "treaty", f"{names[t['b_id']]} accepted your pact", view(t, t["a_id"], names))
        game.event(tx, t["a_id"], "treaty.accepted", view(t, t["a_id"], names))
        await record(game, tx, "treaty", f"{names[t['a_id']]} and {names[t['b_id']]} swore a pact", player_id=t["a_id"])
        return view(t, player_id, names)


@router.delete("/treaties/{treaty_id}")
async def end(treaty_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Withdraw or decline a proposal, or give notice on a pact."""
    async with game.tx() as tx:
        t = await tx.conn.fetchrow("SELECT * FROM treaties WHERE id = $1 FOR UPDATE", treaty_id)
        if t is None or player_id not in (t["a_id"], t["b_id"]):
            raise not_found("treaty_not_found")
        other = t["b_id"] if t["a_id"] == player_id else t["a_id"]
        names = await _names(tx.conn, t["a_id"], t["b_id"])
        if t["status"] == "proposed":
            await tx.conn.execute("DELETE FROM treaties WHERE id = $1", treaty_id)
            game.event(tx, other, "treaty.ended", {"id": treaty_id, "with": {"id": player_id, "name": names[player_id]}, "reason": "declined"})
            return {"ended": True}
        if t["ends_at"]:
            return view(t, player_id, names)
        ends = game.clock.now() + int(cfg(game)["notice_hours"] * 3_600_000)
        t = await tx.conn.fetchrow("UPDATE treaties SET ends_at = $2 WHERE id = $1 RETURNING *", treaty_id, ends)
        await game.schedule(tx, END, ends, {"treaty": treaty_id})
        await add_report(game, tx, other, "treaty", f"{names[player_id]} gave notice on your pact", view(t, other, names))
        return view(t, player_id, names)


async def on_end(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    t = await tx.conn.fetchrow("DELETE FROM treaties WHERE id = $1 AND ends_at IS NOT NULL RETURNING *", job["payload"]["treaty"])
    if t is not None:
        for p in (t["a_id"], t["b_id"]):
            game.event(tx, p, "treaty.ended", {"id": t["id"], "reason": "notice"})


async def on_tribute(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    from .villages import push_village

    t = await tx.conn.fetchrow("SELECT * FROM treaties WHERE id = $1 AND status = 'active' FOR UPDATE", job["payload"]["treaty"])
    if t is None or not t["tribute"]:
        return
    trib = t["tribute"]
    payee_id = t["b_id"] if trib["payer"] == t["a_id"] else t["a_id"]
    payer, payee = await first_city(tx.conn, trib["payer"]), await first_city(tx.conn, payee_id)
    names = await _names(tx.conn, t["a_id"], t["b_id"])
    if payer is None or payee is None:
        await tx.conn.execute("DELETE FROM treaties WHERE id = $1", t["id"])
        return
    await accrue(game, tx, payer)
    if any(payer.state["resources"].get(r, 0) < n for r, n in trib["resources"].items()):
        await tx.conn.execute("DELETE FROM treaties WHERE id = $1", t["id"])
        for p in (t["a_id"], t["b_id"]):
            await add_report(game, tx, p, "treaty", f"The pact between {names[t['a_id']]} and {names[t['b_id']]} lapsed: the tribute went unpaid",
                             {"with": names[t["b_id"] if p == t["a_id"] else t["a_id"]], "tribute": trib["resources"]})
        return
    for r, n in trib["resources"].items():
        payer.state["resources"][r] -= n
    await save_village(game, tx, payer)
    await accrue(game, tx, payee)
    payee.state = game.engine.deposit(payee.state, trib["resources"])
    await save_village(game, tx, payee)
    now = game.clock.now()
    await tx.conn.execute("UPDATE treaties SET last_paid_at = $2 WHERE id = $1", t["id"], now)
    game.event(tx, payee.player_id, "treaty.tribute", {"from": payer.public(), "resources": trib["resources"]})
    await push_village(game, tx, payer)
    await push_village(game, tx, payee)
    if not t["ends_at"] or t["ends_at"] > now + int(trib["every_ms"]):
        await game.schedule(tx, TRIBUTE, now + int(trib["every_ms"]), {"treaty": t["id"]})


async def break_pact(game: Game, tx: Tx, t: asyncpg.Record, breaker: int, target: VillageRow) -> None:
    from .chronicle import record
    from .contentment import add_effect, schedule_end
    from ..repo import refresh_all

    c = cfg(game)
    victim = t["b_id"] if t["a_id"] == breaker else t["a_id"]
    await tx.conn.execute("DELETE FROM treaties WHERE id = $1", t["id"])
    names = await _names(tx.conn, breaker, victim)
    now = game.clock.now()
    pmeta = await tx.conn.fetchval("SELECT meta FROM players WHERE id = $1 FOR UPDATE", breaker) or {}
    pmeta["treacherous_until"] = now + int(c["treachery_hours"] * 3_600_000)
    until = add_effect(game, pmeta, "contentment", f"Broke the pact with {names[victim]}", c["treachery_mood"],
                       c["treachery_hours"] * game.content.pack["world"]["speed"])  # add_effect counts game hours
    await tx.conn.execute("UPDATE players SET meta = $2 WHERE id = $1", breaker, pmeta)
    await schedule_end(game, tx, until, player_id=breaker)
    await refresh_all(game, breaker, tx=tx)
    data = {"breaker": {"id": breaker, "name": names[breaker]}, "target": target.public(), "until": pmeta["treacherous_until"]}
    await add_report(game, tx, victim, "treaty", f"{names[breaker]} broke your pact and marches on {target.name}", data)
    game.event(tx, breaker, "treaty.broken", data)
    await record(game, tx, "treachery", f"{names[breaker]} broke their pact with {names[victim]}", village=target, data=data)


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    if order.get("type") != "send" or order.get("kind") not in ("attack", "raid"):
        return
    target_player = (order.get("target") or {}).get("player_id")
    if not target_player or target_player == player["id"]:
        return
    t = await pact_between(tx.conn, player["id"], target_player)
    if t is not None and t["status"] == "active":
        target = await get_village(tx.conn, order["target"]["id"])
        await break_pact(game, tx, t, player["id"], target)


module = Module("treaties", router=router, jobs={TRIBUTE: on_tribute, END: on_end})
