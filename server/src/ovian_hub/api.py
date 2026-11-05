"""Accounts, worlds, badges and founders."""

from __future__ import annotations

import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ovian_server.errors import GameError, rule
from ovian_server.security import hash_password, verify_password

from .config import HubSettings
from .hub import AccountId, AdminId, HubDep, require_world_key

router = APIRouter()
USERNAME = re.compile(r"^[A-Za-z0-9_\-]{3,24}$")
BADGE_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,31}$")
WORLD_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,31}$")
WORLD_FIELDS = "id, name, description, pack, speed, api_url, status, founders_only, patrons_early, starts_at, ends_at, sort"


# ---------------------------------------------------------------- accounts

class Register(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=200)
    email: str | None = Field(default=None, max_length=200)


class Login(BaseModel):
    username: str
    password: str


async def _login(hub: Any, account_id: int, username: str) -> dict[str, Any]:
    admins = [u.lower() for u in HubSettings.split(hub.settings.admin_users)]
    await hub.pool.execute(
        "UPDATE accounts SET last_login_at = $2, is_admin = is_admin OR lower(username) = ANY($3::text[]) WHERE id = $1",
        account_id, hub.now(), admins)
    return {"token": hub.login_token(account_id, username), "account": await hub.profile(hub.pool, account_id)}


@router.post("/auth/register", status_code=201)
async def register(body: Register, hub: HubDep) -> dict[str, Any]:
    if not USERNAME.match(body.username):
        raise GameError(422, "invalid_username", "3-24 letters, digits, _ or -")
    email = (body.email or "").strip() or None
    if email and "@" not in email:
        raise GameError(422, "invalid_email")
    if await hub.pool.fetchval("SELECT 1 FROM accounts WHERE lower(username) = lower($1)", body.username):
        raise rule("username_taken")
    for _, answer in await hub.ask_worlds("name", {"username": body.username}):
        if answer.get("taken"):
            raise rule("name_in_world", "a player of this name already lives in a world: log in with that player's password instead")
    try:
        account_id = await hub.pool.fetchval(
            "INSERT INTO accounts(username, password_hash, email, created_at) VALUES ($1, $2, $3, $4) RETURNING id",
            body.username, await hash_password(body.password), email, hub.now())
    except asyncpg.UniqueViolationError as e:
        raise rule("username_taken") from e
    return await _login(hub, account_id, body.username)


@router.post("/auth/login")
async def login(body: Login, hub: HubDep) -> dict[str, Any]:
    """Log in. A player who lived in a world before the hub logs in with that world's name and password: the hub
    account is created with them, and the player is linked to it (in every world where the same name and password match)."""
    r = await hub.pool.fetchrow("SELECT id, username, password_hash FROM accounts WHERE lower(username) = lower($1)", body.username)
    if r is not None:
        if not await verify_password(body.password, r["password_hash"]):
            raise GameError(401, "invalid_credentials")
        return await _login(hub, r["id"], r["username"])
    if not USERNAME.match(body.username):
        raise GameError(401, "invalid_credentials")
    found = [(w, a) for w, a in await hub.ask_worlds("claim", {"username": body.username, "password": body.password}) if a.get("ok")]
    if not found:
        raise GameError(401, "invalid_credentials")
    name = found[0][1].get("username") or body.username
    try:
        account_id = await hub.pool.fetchval(
            "INSERT INTO accounts(username, password_hash, created_at) VALUES ($1, $2, $3) RETURNING id",
            name, await hash_password(body.password), hub.now())
    except asyncpg.UniqueViolationError as e:
        raise GameError(401, "invalid_credentials") from e
    for world_id, answer in await hub.ask_worlds("claim", {"username": name, "password": body.password, "account_id": account_id}):
        if answer.get("ok"):
            await hub.pool.execute(
                """INSERT INTO memberships(account_id, world_id, player_id, joined_at) VALUES ($1, $2, $3, $4)
                   ON CONFLICT (account_id, world_id) DO UPDATE SET player_id = EXCLUDED.player_id""",
                account_id, world_id, answer["player_id"], hub.now())
    return await _login(hub, account_id, name)


@router.get("/me")
async def me(account_id: AccountId, hub: HubDep) -> dict[str, Any]:
    async with hub.pool.acquire() as conn:
        profile = await hub.profile(conn, account_id)
        a = await conn.fetchrow("SELECT email, is_admin, created_at, founder_since FROM accounts WHERE id = $1", account_id)
        link = await conn.fetchrow("SELECT patron_status, tier_ids, cents, linked_at FROM patreon_links WHERE account_id = $1", account_id)
        worlds = await conn.fetch("SELECT world_id, player_id, joined_at FROM memberships WHERE account_id = $1 ORDER BY joined_at", account_id)
    return profile | {
        "email": a["email"], "is_admin": a["is_admin"], "created_at": a["created_at"], "founder_since": a["founder_since"],
        "patreon": dict(link) | {"tier_ids": list(link["tier_ids"])} if link else None,
        "patreon_enabled": bool(hub.settings.patreon_client_id),
        "worlds": [dict(w) for w in worlds],
    }


class ChangePassword(BaseModel):
    password: str
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/me/password")
async def change_password(body: ChangePassword, account_id: AccountId, hub: HubDep) -> dict[str, Any]:
    stored = await hub.pool.fetchval("SELECT password_hash FROM accounts WHERE id = $1", account_id)
    if not await verify_password(body.password, stored):
        raise GameError(401, "invalid_credentials", "wrong password")
    await hub.pool.execute("UPDATE accounts SET password_hash = $2 WHERE id = $1", account_id, await hash_password(body.new_password))
    return {"ok": True}


@router.get("/accounts/{username}")
async def public_profile(username: str, hub: HubDep) -> dict[str, Any]:
    account_id = await hub.pool.fetchval("SELECT id FROM accounts WHERE lower(username) = lower($1)", username)
    if account_id is None:
        raise GameError(404, "account_not_found")
    return await hub.profile(hub.pool, account_id)


@router.get("/founders")
async def founders(hub: HubDep) -> list[dict[str, Any]]:
    """The founders' roll, in order."""
    rows = await hub.pool.fetch(
        "SELECT username, founder_no, founder_since FROM accounts WHERE founder ORDER BY founder_no NULLS LAST, founder_since, id")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- worlds

async def _can_join(hub: Any, w: dict[str, Any], account_id: int | None) -> str | None:
    """Why an account may not enter a world, or None."""
    if w["status"] in ("upcoming", "ended"):
        return f"world_{w['status']}"
    if account_id is None:
        return "unauthorized"
    joined = await hub.pool.fetchval("SELECT 1 FROM memberships WHERE account_id = $1 AND world_id = $2", account_id, w["id"])
    if joined:
        return None
    if w["status"] == "closed":
        return "world_closed"
    if w["founders_only"]:
        a = await hub.pool.fetchrow(
            """SELECT a.founder, coalesce(p.patron_status = 'active_patron', false) AS patron
               FROM accounts a LEFT JOIN patreon_links p ON p.account_id = a.id WHERE a.id = $1""", account_id)
        if not (a["founder"] or (w["patrons_early"] and a["patron"])):
            return "early_access_only"
    return None


@router.get("/worlds")
async def worlds(hub: HubDep) -> list[dict[str, Any]]:
    rows = await hub.pool.fetch(
        f"""SELECT {WORLD_FIELDS}, (SELECT count(*) FROM memberships m WHERE m.world_id = w.id)::int AS players
            FROM worlds w WHERE status <> 'ended' OR ends_at > $1 - 30 * 86400000::bigint ORDER BY sort, created_at""", hub.now())
    return [dict(r) for r in rows]


@router.get("/me/worlds")
async def my_worlds(account_id: AccountId, hub: HubDep) -> list[dict[str, Any]]:
    """Every world, with whether this account plays there and whether it may join."""
    out = []
    for w in await worlds(hub):
        player_id = await hub.pool.fetchval("SELECT player_id FROM memberships WHERE account_id = $1 AND world_id = $2", account_id, w["id"])
        blocked = await _can_join(hub, w, account_id)
        out.append(w | {"player_id": player_id, "joined": player_id is not None, "can_enter": blocked is None, "blocked": blocked})
    return out


@router.post("/worlds/{world_id}/ticket")
async def ticket(world_id: str, account_id: AccountId, hub: HubDep) -> dict[str, Any]:
    """A pass into a world, valid a few minutes: hand it to the world's POST /auth/hub."""
    w = await hub.pool.fetchrow(f"SELECT {WORLD_FIELDS} FROM worlds WHERE id = $1", world_id)
    if w is None:
        raise GameError(404, "world_not_found")
    blocked = await _can_join(hub, dict(w), account_id)
    if blocked:
        raise rule(blocked)
    profile = await hub.profile(hub.pool, account_id)
    return {"ticket": hub.ticket(world_id, profile), "world": dict(w), "expires_in": hub.settings.ticket_ttl_seconds}


class Joined(BaseModel):
    account_id: int
    player_id: int


@router.post("/internal/worlds/{world_id}/members", dependencies=[Depends(require_world_key)], include_in_schema=False)
async def world_member(world_id: str, body: Joined, hub: HubDep) -> dict[str, Any]:
    """A world tells the hub that an account now has a player there (or a new one)."""
    await hub.pool.execute(
        """INSERT INTO memberships(account_id, world_id, player_id, joined_at) VALUES ($1, $2, $3, $4)
           ON CONFLICT (account_id, world_id) DO UPDATE SET player_id = EXCLUDED.player_id""",
        body.account_id, world_id, body.player_id, hub.now())
    return {"ok": True}


@router.delete("/internal/worlds/{world_id}/members/{account_id}", dependencies=[Depends(require_world_key)], include_in_schema=False)
async def world_member_left(world_id: str, account_id: int, hub: HubDep) -> dict[str, Any]:
    await hub.pool.execute("DELETE FROM memberships WHERE account_id = $1 AND world_id = $2", account_id, world_id)
    return {"ok": True}


# ---------------------------------------------------------------- badges

@router.get("/badges")
async def badges(hub: HubDep) -> list[dict[str, Any]]:
    rows = await hub.pool.fetch(
        """SELECT b.id, b.name, b.description, b.icon, b.color, b.kind, b.patreon_tier, b.sort,
                  (SELECT count(*) FROM account_badges ab WHERE ab.badge_id = b.id)::int AS holders
           FROM badges b ORDER BY b.sort, b.name""")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- administration

@router.get("/admin/accounts")
async def admin_accounts(_: AdminId, hub: HubDep, q: str = "", limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    rows = await hub.pool.fetch(
        """SELECT a.id, a.username, a.email, a.created_at, a.last_login_at, a.is_admin, a.founder, a.founder_no,
                  p.patron_status, p.cents,
                  coalesce((SELECT array_agg(badge_id ORDER BY badge_id) FROM account_badges WHERE account_id = a.id), '{}') AS badges
           FROM accounts a LEFT JOIN patreon_links p ON p.account_id = a.id
           WHERE $1 = '' OR a.username ILIKE '%' || $1 || '%' OR a.email ILIKE '%' || $1 || '%'
           ORDER BY a.founder DESC, a.founder_no NULLS LAST, a.id LIMIT $2""", q.strip(), limit)
    return [dict(r) | {"badges": list(r["badges"])} for r in rows]


class Founder(BaseModel):
    founder: bool
    #: Founder number; default the next free one.
    number: int | None = Field(default=None, ge=1)
    #: Badges to give with founder status; default every badge of kind "founder".
    badges: list[str] | None = None


@router.post("/admin/accounts/{account_id}/founder")
async def set_founder(account_id: int, body: Founder, admin_id: AdminId, hub: HubDep) -> dict[str, Any]:
    """Make an account a founder (with its founder badges), or take it back."""
    now = hub.now()
    try:
        async with hub.pool.acquire() as conn, conn.transaction():
            a = await conn.fetchrow("SELECT id, founder, founder_no FROM accounts WHERE id = $1 FOR UPDATE", account_id)
            if a is None:
                raise GameError(404, "account_not_found")
            if body.founder:
                number = body.number or a["founder_no"] or (await conn.fetchval("SELECT coalesce(max(founder_no), 0) + 1 FROM accounts"))
                await conn.execute(
                    "UPDATE accounts SET founder = true, founder_no = $2, founder_since = coalesce(founder_since, $3) WHERE id = $1",
                    account_id, number, now)
                wanted = body.badges if body.badges is not None else [
                    r["id"] for r in await conn.fetch("SELECT id FROM badges WHERE kind = 'founder'")]
                known = {r["id"] for r in await conn.fetch("SELECT id FROM badges WHERE id = ANY($1::text[])", wanted)}
                if missing := sorted(set(wanted) - known):
                    raise GameError(404, "badge_not_found", ", ".join(missing))
                await conn.execute("DELETE FROM account_badges WHERE account_id = $1 AND source = 'founder' AND NOT badge_id = ANY($2::text[])",
                                   account_id, wanted)
                for b in wanted:
                    await conn.execute(
                        """INSERT INTO account_badges(account_id, badge_id, source, granted_at, granted_by) VALUES ($1, $2, 'founder', $3, $4)
                           ON CONFLICT (account_id, badge_id) DO NOTHING""", account_id, b, now, admin_id)
            else:
                await conn.execute("UPDATE accounts SET founder = false, founder_no = NULL, founder_since = NULL WHERE id = $1", account_id)
                await conn.execute("DELETE FROM account_badges WHERE account_id = $1 AND source = 'founder'", account_id)
    except asyncpg.UniqueViolationError as e:
        raise rule("founder_number_taken") from e
    await hub.push_profile(account_id)
    return await hub.profile(hub.pool, account_id)


class Grant(BaseModel):
    note: str = Field(default="", max_length=200)


@router.post("/admin/accounts/{account_id}/badges/{badge_id}")
async def grant_badge(account_id: int, badge_id: str, body: Grant, admin_id: AdminId, hub: HubDep) -> dict[str, Any]:
    try:
        await hub.pool.execute(
            """INSERT INTO account_badges(account_id, badge_id, source, granted_at, granted_by, note) VALUES ($1, $2, 'admin', $3, $4, $5)
               ON CONFLICT (account_id, badge_id) DO UPDATE SET note = EXCLUDED.note""",
            account_id, badge_id, hub.now(), admin_id, body.note)
    except asyncpg.ForeignKeyViolationError as e:
        raise GameError(404, "badge_or_account_not_found") from e
    await hub.push_profile(account_id)
    return await hub.profile(hub.pool, account_id)


@router.delete("/admin/accounts/{account_id}/badges/{badge_id}")
async def revoke_badge(account_id: int, badge_id: str, _: AdminId, hub: HubDep) -> dict[str, Any]:
    await hub.pool.execute("DELETE FROM account_badges WHERE account_id = $1 AND badge_id = $2", account_id, badge_id)
    await hub.push_profile(account_id)
    return await hub.profile(hub.pool, account_id)


class Badge(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=300)
    icon: str = Field(default="", max_length=8)
    color: str = Field(default="#b8892c", pattern=r"^#[0-9a-fA-F]{6}$")
    kind: str = Field(default="award", pattern="^(founder|patron|award)$")
    patreon_tier: str | None = Field(default=None, max_length=40)
    sort: int = 0


@router.put("/admin/badges/{badge_id}")
async def put_badge(badge_id: str, body: Badge, _: AdminId, hub: HubDep) -> dict[str, Any]:
    if not BADGE_ID.match(badge_id):
        raise GameError(422, "invalid_badge_id", "2-32 lowercase letters, digits, _ or -")
    if body.kind == "patron" and not body.patreon_tier:
        raise GameError(422, "patreon_tier_required", "a tier id, or * for any pledge")
    await hub.pool.execute(
        """INSERT INTO badges(id, name, description, icon, color, kind, patreon_tier, sort, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (id) DO UPDATE SET name = $2, description = $3, icon = $4, color = $5, kind = $6, patreon_tier = $7, sort = $8""",
        badge_id, body.name, body.description, body.icon, body.color, body.kind,
        body.patreon_tier if body.kind == "patron" else None, body.sort, hub.now())
    if body.kind == "patron":
        from .patreon import sync_all

        await sync_all(hub)
    for account_id in [r["account_id"] for r in await hub.pool.fetch("SELECT account_id FROM account_badges WHERE badge_id = $1", badge_id)]:
        await hub.push_profile(account_id)
    return dict(await hub.pool.fetchrow("SELECT * FROM badges WHERE id = $1", badge_id))


@router.delete("/admin/badges/{badge_id}")
async def delete_badge(badge_id: str, _: AdminId, hub: HubDep) -> dict[str, Any]:
    holders = [r["account_id"] for r in await hub.pool.fetch("SELECT account_id FROM account_badges WHERE badge_id = $1", badge_id)]
    if not await hub.pool.fetchval("DELETE FROM badges WHERE id = $1 RETURNING true", badge_id):
        raise GameError(404, "badge_not_found")
    for account_id in holders:
        await hub.push_profile(account_id)
    return {"deleted": True}


class World(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=1000)
    pack: str = ""
    speed: float = 1
    api_url: str = Field(min_length=1, max_length=300)
    internal_url: str = Field(default="", max_length=300)
    status: str = Field(default="open", pattern="^(upcoming|open|closed|ended)$")
    founders_only: bool = False
    patrons_early: bool = False
    starts_at: int | None = None
    ends_at: int | None = None
    sort: int = 0


async def upsert_world(hub: Any, world_id: str, w: World) -> dict[str, Any]:
    if not WORLD_ID.match(world_id):
        raise GameError(422, "invalid_world_id", "1-32 lowercase letters, digits, _ or -")
    row = await hub.pool.fetchrow(
        f"""INSERT INTO worlds(id, name, description, pack, speed, api_url, internal_url, status, founders_only, patrons_early,
                              starts_at, ends_at, sort, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
           ON CONFLICT (id) DO UPDATE SET name = $2, description = $3, pack = $4, speed = $5, api_url = $6, internal_url = $7,
               status = $8, founders_only = $9, patrons_early = $10, starts_at = $11, ends_at = $12, sort = $13
           RETURNING {WORLD_FIELDS}, internal_url""",
        world_id, w.name, w.description, w.pack, w.speed, w.api_url, w.internal_url, w.status, w.founders_only,
        w.patrons_early, w.starts_at, w.ends_at, w.sort, hub.now())
    return dict(row)


@router.put("/admin/worlds/{world_id}")
async def put_world(world_id: str, body: World, _: AdminId, hub: HubDep) -> dict[str, Any]:
    return await upsert_world(hub, world_id, body)


@router.get("/admin/worlds")
async def admin_worlds(_: AdminId, hub: HubDep) -> list[dict[str, Any]]:
    rows = await hub.pool.fetch(f"SELECT {WORLD_FIELDS}, internal_url FROM worlds ORDER BY sort, created_at")
    return [dict(r) for r in rows]


@router.delete("/admin/worlds/{world_id}")
async def delete_world(world_id: str, _: AdminId, hub: HubDep) -> dict[str, Any]:
    """Remove a world from the list (its own server and database are untouched)."""
    if not await hub.pool.fetchval("DELETE FROM worlds WHERE id = $1 RETURNING true", world_id):
        raise GameError(404, "world_not_found")
    return {"deleted": True}
