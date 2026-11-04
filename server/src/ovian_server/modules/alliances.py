"""Alliances: members and roles, invitations, diplomacy, a private chat and shared battle reports.

- Roles: ``leader`` (one), ``officer`` (invite, kick members, diplomacy), ``member``.
- Diplomacy between alliances: ``ally`` and ``nap`` (non-aggression pact) need the
  other side to accept; ``war`` is declared unilaterally. ``none`` ends any of them.
- Members, allies and pact partners cannot attack, raid or scout each other.
- Alliance chat reaches members as ``alliance.message`` events on their own topic,
  so no other player can subscribe to it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

import asyncpg
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import GameError, forbidden, not_found, rule
from ..hooks import hookimpl
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

router = APIRouter(tags=["alliances"])
TAG = re.compile(r"^[A-Za-z0-9_\-]{2,8}$")
RANK = {"leader": 3, "officer": 2, "member": 1}


async def membership(conn: asyncpg.Connection, player_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT m.alliance_id, m.role, a.name, a.tag FROM alliance_members m JOIN alliances a ON a.id = m.alliance_id WHERE m.player_id = $1",
        player_id,
    )


async def relation(conn: asyncpg.Connection, a_player: int, b_player: int) -> str | None:
    """How two players stand: self, member (same alliance), ally, nap, war, or None."""
    if a_player == b_player:
        return "self"
    rows = await conn.fetch("SELECT player_id, alliance_id FROM alliance_members WHERE player_id = ANY($1::bigint[])", [a_player, b_player])
    by = {r["player_id"]: r["alliance_id"] for r in rows}
    a, b = by.get(a_player), by.get(b_player)
    if a is None or b is None:
        return None
    if a == b:
        return "member"
    return await conn.fetchval("SELECT kind FROM diplomacy WHERE alliance_id = $1 AND other_id = $2 AND status = 'active'", a, b)


async def _mine(conn: asyncpg.Connection, player_id: int, at_least: str = "member") -> asyncpg.Record:
    m = await membership(conn, player_id)
    if m is None:
        raise rule("no_alliance", "you are not in an alliance")
    if RANK[m["role"]] < RANK[at_least]:
        raise forbidden("alliance_rank")
    return m


async def _member_ids(conn: asyncpg.Connection, alliance_id: int) -> list[int]:
    return [r["player_id"] for r in await conn.fetch("SELECT player_id FROM alliance_members WHERE alliance_id = $1", alliance_id)]


async def notify(game: Game, tx: Tx, alliance_id: int, type_: str, data: dict[str, Any]) -> None:
    for pid in await _member_ids(tx.conn, alliance_id):
        game.event(tx, pid, type_, data)


async def _summary(conn: asyncpg.Connection, alliance_id: int) -> dict[str, Any]:
    a = await conn.fetchrow("SELECT * FROM alliances WHERE id = $1", alliance_id)
    if a is None:
        raise not_found("alliance_not_found")
    members = await conn.fetch(
        """SELECT p.id, p.username, p.tribe, m.role, m.joined_at, coalesce(sum(v.population), 0)::int AS population,
                  count(v.id)::int AS villages, coalesce(sum(v.culture), 0)::float AS culture
           FROM alliance_members m JOIN players p ON p.id = m.player_id LEFT JOIN villages v ON v.player_id = p.id
           WHERE m.alliance_id = $1 GROUP BY p.id, m.role, m.joined_at ORDER BY array_position(ARRAY['leader','officer','member'], m.role), population DESC""",
        alliance_id,
    )
    diplomacy = await conn.fetch(
        """SELECT d.other_id, d.kind, d.status, d.since, o.name, o.tag,
                  (SELECT status FROM diplomacy r WHERE r.alliance_id = d.other_id AND r.other_id = d.alliance_id) AS their_status
           FROM diplomacy d JOIN alliances o ON o.id = d.other_id WHERE d.alliance_id = $1 ORDER BY d.kind, o.tag""",
        alliance_id,
    )
    incoming = await conn.fetch(
        """SELECT d.alliance_id AS other_id, d.kind, o.name, o.tag FROM diplomacy d JOIN alliances o ON o.id = d.alliance_id
           WHERE d.other_id = $1 AND d.status = 'proposed'
             AND NOT EXISTS (SELECT 1 FROM diplomacy x WHERE x.alliance_id = $1 AND x.other_id = d.alliance_id AND x.status = 'active')""",
        alliance_id,
    )
    return dict(a) | {
        "members": [dict(m) for m in members],
        "population": sum(m["population"] for m in members),
        "diplomacy": [dict(d) for d in diplomacy if d["status"] == "active" or d["their_status"] is None],
        "proposals": [dict(d) for d in incoming],
    }


@router.get("/alliances")
async def list_alliances(game: GameDep) -> list[dict[str, Any]]:
    """Every alliance with its size, population and culture, largest first."""
    rows = await game.pool.fetch(
        """SELECT a.id, a.name, a.tag, count(DISTINCT m.player_id)::int AS members,
                  coalesce(sum(v.population), 0)::int AS population, coalesce(sum(v.culture), 0)::float AS culture
           FROM alliances a LEFT JOIN alliance_members m ON m.alliance_id = a.id LEFT JOIN villages v ON v.player_id = m.player_id
           GROUP BY a.id ORDER BY population DESC, a.id"""
    )
    return [dict(r) | {"rank": i + 1} for i, r in enumerate(rows)]


@router.get("/alliances/{alliance_id}")
async def get_alliance(alliance_id: int, game: GameDep) -> dict[str, Any]:
    async with game.pool.acquire() as conn:
        return await _summary(conn, alliance_id)


@router.get("/alliance")
async def my_alliance(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Your alliance (or null) and the invitations you have received."""
    async with game.pool.acquire() as conn:
        m = await membership(conn, player_id)
        invites = await conn.fetch(
            """SELECT a.id, a.name, a.tag, p.username AS invited_by, i.created_at FROM alliance_invites i
               JOIN alliances a ON a.id = i.alliance_id LEFT JOIN players p ON p.id = i.invited_by WHERE i.player_id = $1""",
            player_id,
        )
        out: dict[str, Any] = {"alliance": None, "role": None, "invites": [dict(i) for i in invites]}
        if m:
            out["alliance"] = await _summary(conn, m["alliance_id"])
            out["role"] = m["role"]
            out["sent_invites"] = [dict(r) for r in await conn.fetch(
                "SELECT p.id, p.username FROM alliance_invites i JOIN players p ON p.id = i.player_id WHERE i.alliance_id = $1", m["alliance_id"])]
        return out


class Found(BaseModel):
    name: str = Field(min_length=3, max_length=40)
    tag: str
    description: str = Field("", max_length=2000)


@router.post("/alliances", status_code=201)
async def found(body: Found, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    if not TAG.match(body.tag):
        raise GameError(422, "invalid_tag", "2-8 letters, digits, _ or -")
    async with game.tx() as tx:
        if await membership(tx.conn, player_id):
            raise rule("already_in_alliance")
        try:
            aid = await tx.conn.fetchval(
                "INSERT INTO alliances(name, tag, description, created_at) VALUES ($1, $2, $3, $4) RETURNING id",
                body.name.strip(), body.tag, body.description, game.clock.now(),
            )
        except asyncpg.UniqueViolationError as e:
            raise rule("alliance_taken", "that name or tag is taken") from e
        await tx.conn.execute("INSERT INTO alliance_members(player_id, alliance_id, role, joined_at) VALUES ($1, $2, 'leader', $3)",
                              player_id, aid, game.clock.now())
        await tx.conn.execute("DELETE FROM alliance_invites WHERE player_id = $1", player_id)
        from .chronicle import player_name, record

        await record(game, tx, "alliance", f"{await player_name(tx.conn, player_id)} founded the alliance [{body.tag}] {body.name.strip()}",
                     player_id=player_id, data={"alliance": {"id": aid, "tag": body.tag}})
        return await _summary(tx.conn, aid)


class Describe(BaseModel):
    description: str = Field(max_length=2000)


@router.patch("/alliance")
async def describe(body: Describe, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "officer")
        await tx.conn.execute("UPDATE alliances SET description = $2 WHERE id = $1", m["alliance_id"], body.description)
        return await _summary(tx.conn, m["alliance_id"])


class Invite(BaseModel):
    username: str


@router.post("/alliance/invites", status_code=201)
async def invite(body: Invite, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "officer")
        target = await tx.conn.fetchrow("SELECT id, username FROM players WHERE lower(username) = lower($1) AND NOT npc", body.username)
        if target is None:
            raise not_found("player_not_found")
        if await membership(tx.conn, target["id"]):
            raise rule("already_in_alliance", "that player is already in an alliance")
        await tx.conn.execute(
            "INSERT INTO alliance_invites(alliance_id, player_id, invited_by, created_at) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            m["alliance_id"], target["id"], player_id, game.clock.now(),
        )
        game.event(tx, target["id"], "alliance.invited", {"alliance": {"id": m["alliance_id"], "name": m["name"], "tag": m["tag"]}})
        return {"invited": dict(target)}


@router.delete("/alliance/invites/{target_id}")
async def withdraw(target_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "officer")
        await tx.conn.execute("DELETE FROM alliance_invites WHERE alliance_id = $1 AND player_id = $2", m["alliance_id"], target_id)
        return {"ok": True}


@router.post("/alliances/{alliance_id}/join")
async def join(alliance_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Accept an invitation."""
    async with game.tx() as tx:
        if await membership(tx.conn, player_id):
            raise rule("already_in_alliance")
        if not await tx.conn.fetchval("DELETE FROM alliance_invites WHERE alliance_id = $1 AND player_id = $2 RETURNING 1", alliance_id, player_id):
            raise not_found("invite_not_found")
        await tx.conn.execute("DELETE FROM alliance_invites WHERE player_id = $1", player_id)
        await tx.conn.execute("INSERT INTO alliance_members(player_id, alliance_id, role, joined_at) VALUES ($1, $2, 'member', $3)",
                              player_id, alliance_id, game.clock.now())
        name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
        await notify(game, tx, alliance_id, "alliance.joined", {"player": {"id": player_id, "name": name}})
        return await _summary(tx.conn, alliance_id)


@router.post("/alliance/invites/{alliance_id}/decline")
async def decline(alliance_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        await tx.conn.execute("DELETE FROM alliance_invites WHERE alliance_id = $1 AND player_id = $2", alliance_id, player_id)
        return {"ok": True}


async def _remove(game: Game, tx: Tx, alliance_id: int, player_id: int, reason: str) -> None:
    role = await tx.conn.fetchval("DELETE FROM alliance_members WHERE player_id = $1 RETURNING role", player_id)
    left = await tx.conn.fetch("SELECT player_id, role FROM alliance_members WHERE alliance_id = $1 ORDER BY array_position(ARRAY['officer','member'], role), joined_at", alliance_id)
    if not left:
        await tx.conn.execute("DELETE FROM alliances WHERE id = $1", alliance_id)
        return
    if role == "leader":
        await tx.conn.execute("UPDATE alliance_members SET role = 'leader' WHERE player_id = $1", left[0]["player_id"])
    await notify(game, tx, alliance_id, "alliance.left", {"player_id": player_id, "reason": reason})
    game.event(tx, player_id, "alliance.left", {"player_id": player_id, "reason": reason})


@router.post("/alliance/leave")
async def leave(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id)
        await _remove(game, tx, m["alliance_id"], player_id, "left")
        return {"ok": True}


@router.post("/alliance/members/{member_id}/kick")
async def kick(member_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "officer")
        target = await membership(tx.conn, member_id)
        if target is None or target["alliance_id"] != m["alliance_id"] or member_id == player_id:
            raise not_found("member_not_found")
        if RANK[target["role"]] >= RANK[m["role"]]:
            raise forbidden("alliance_rank")
        await _remove(game, tx, m["alliance_id"], member_id, "kicked")
        return await _summary(tx.conn, m["alliance_id"])


class Role(BaseModel):
    role: Literal["leader", "officer", "member"]


@router.post("/alliance/members/{member_id}/role")
async def set_role(member_id: int, body: Role, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Leaders promote and demote; making someone leader hands over the leadership."""
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "leader")
        target = await membership(tx.conn, member_id)
        if target is None or target["alliance_id"] != m["alliance_id"] or member_id == player_id:
            raise not_found("member_not_found")
        await tx.conn.execute("UPDATE alliance_members SET role = $2 WHERE player_id = $1", member_id, body.role)
        if body.role == "leader":
            await tx.conn.execute("UPDATE alliance_members SET role = 'officer' WHERE player_id = $1", player_id)
        await notify(game, tx, m["alliance_id"], "alliance.role", {"player_id": member_id, "role": body.role})
        return await _summary(tx.conn, m["alliance_id"])


class Stance(BaseModel):
    tag: str
    kind: Literal["ally", "nap", "war", "none"]


@router.post("/alliance/diplomacy")
async def diplomacy(body: Stance, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Propose an alliance or pact (the other side must propose the same back), declare war, or end relations."""
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id, "officer")
        other = await tx.conn.fetchrow("SELECT id, name, tag FROM alliances WHERE lower(tag) = lower($1)", body.tag)
        if other is None or other["id"] == m["alliance_id"]:
            raise not_found("alliance_not_found")
        a, b, now = m["alliance_id"], other["id"], game.clock.now()
        agreed = False
        if body.kind == "none":
            await tx.conn.execute("DELETE FROM diplomacy WHERE (alliance_id = $1 AND other_id = $2) OR (alliance_id = $2 AND other_id = $1)", a, b)
        elif body.kind == "war":
            for x, y in ((a, b), (b, a)):
                await tx.conn.execute(
                    """INSERT INTO diplomacy(alliance_id, other_id, kind, status, since) VALUES ($1, $2, 'war', 'active', $3)
                       ON CONFLICT (alliance_id, other_id) DO UPDATE SET kind = 'war', status = 'active', since = $3""", x, y, now)
        else:
            theirs = await tx.conn.fetchrow("SELECT kind, status FROM diplomacy WHERE alliance_id = $1 AND other_id = $2", b, a)
            agreed = theirs is not None and theirs["kind"] == body.kind and theirs["status"] == "proposed"
            await tx.conn.execute(
                """INSERT INTO diplomacy(alliance_id, other_id, kind, status, since) VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (alliance_id, other_id) DO UPDATE SET kind = $3, status = $4, since = $5""",
                a, b, body.kind, "active" if agreed else "proposed", now)
            if agreed:
                await tx.conn.execute("UPDATE diplomacy SET status = 'active', since = $3 WHERE alliance_id = $1 AND other_id = $2", b, a, now)
            elif theirs is not None and theirs["status"] == "active":
                # changing an active relation: the old one ends on both sides until agreed again
                await tx.conn.execute("DELETE FROM diplomacy WHERE alliance_id = $1 AND other_id = $2", b, a)
        data = {"alliance": {"id": a, "name": m["name"], "tag": m["tag"]}, "other": dict(other), "kind": body.kind}
        from .chronicle import record

        if body.kind == "war":
            await record(game, tx, "war", f"[{m['tag']}] {m['name']} declared war on [{other['tag']}] {other['name']}", player_id=player_id, data=data)
        elif body.kind != "none" and agreed:
            what = "an alliance" if body.kind == "ally" else "a non-aggression pact"
            await record(game, tx, "pact", f"[{m['tag']}] and [{other['tag']}] swore {what}", player_id=player_id, data=data)
        await notify(game, tx, a, "alliance.diplomacy", data)
        await notify(game, tx, b, "alliance.diplomacy", data)
        return await _summary(tx.conn, a)


class Say(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.get("/alliance/messages")
async def messages(player_id: PlayerId, game: GameDep, limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    async with game.pool.acquire() as conn:
        m = await _mine(conn, player_id)
        rows = await conn.fetch(
            """SELECT x.id, x.text, x.created_at AS at, p.id AS pid, p.username FROM alliance_messages x LEFT JOIN players p ON p.id = x.player_id
               WHERE x.alliance_id = $1 ORDER BY x.id DESC LIMIT $2""", m["alliance_id"], limit)
        return [{"id": r["id"], "text": r["text"], "at": r["at"], "from": {"id": r["pid"], "name": r["username"]}} for r in reversed(rows)]


@router.post("/alliance/messages", status_code=201)
async def say(body: Say, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    async with game.tx() as tx:
        m = await _mine(tx.conn, player_id)
        now = game.clock.now()
        mid = await tx.conn.fetchval("INSERT INTO alliance_messages(alliance_id, player_id, text, created_at) VALUES ($1, $2, $3, $4) RETURNING id",
                                     m["alliance_id"], player_id, body.text.strip(), now)
        name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
        msg = {"id": mid, "text": body.text.strip(), "at": now, "from": {"id": player_id, "name": name}}
        await notify(game, tx, m["alliance_id"], "alliance.message", msg)
        return msg


@router.get("/alliance/reports")
async def shared_reports(player_id: PlayerId, game: GameDep, limit: int = Query(30, ge=1, le=100)) -> list[dict[str, Any]]:
    """Recent battle and scouting reports of every member."""
    async with game.pool.acquire() as conn:
        m = await _mine(conn, player_id)
        rows = await conn.fetch(
            """SELECT r.id, r.kind, r.title, r.created_at, r.data, p.username FROM reports r JOIN alliance_members am ON am.player_id = r.player_id
               JOIN players p ON p.id = r.player_id WHERE am.alliance_id = $1 AND r.kind IN ('battle', 'scout') ORDER BY r.id DESC LIMIT $2""",
            m["alliance_id"], limit)
        return [dict(r) for r in rows]


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    if order["type"] != "send" or order["kind"] not in ("attack", "raid", "scout"):
        return
    rel = await relation(tx.conn, player["id"], order["target"]["player_id"])
    if rel == "member":
        raise rule("same_alliance", "you cannot attack a member of your alliance")
    if rel in ("ally", "nap"):
        raise rule("pact", "your alliance has a pact with theirs")


module = Module("alliances", router=router)
