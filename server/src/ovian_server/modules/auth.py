"""Accounts, tokens and village founding."""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..config import Settings
from ..errors import GameError, rule
from ..repo import VillageRow, get_player, get_village, save_village
from ..security import PlayerId, hash_password, issue_token, require_session, verify_password
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

router = APIRouter(tags=["auth"])
USERNAME = re.compile(r"^[A-Za-z0-9_\-]{3,24}$")


async def found_village(game: Game, tx: Tx, player_id: int, name: str) -> VillageRow:
    """Create a village on a free settleable tile near the centre of the map."""
    rng = random.Random()
    for _ in range(20):
        candidates = game.engine.spawn_candidates(rng.getrandbits(63), 64)
        taken = {
            (r["x"], r["y"])
            for r in await tx.conn.fetch(
                "SELECT x, y FROM villages WHERE (x, y) IN (SELECT * FROM unnest($1::int[], $2::int[]))",
                [c[0] for c in candidates], [c[1] for c in candidates],
            )
        }
        free = [c for c in candidates if c not in taken]
        if not free:
            continue
        x, y = rng.choice(free[:16])
        v = await found_village_at(game, tx, player_id, name, x, y)
        if v is not None:
            return v
    raise GameError(503, "world_full", "no free land left")


async def found_village_at(game: Game, tx: Tx, player_id: int, name: str, x: int, y: int) -> VillageRow | None:
    """Create a village on a given tile; None if the tile is already taken."""
    now = game.clock.now()
    state = game.engine.create_village(now)
    r = await tx.conn.fetchrow(
        """INSERT INTO villages(player_id, name, x, y, state, created_at) VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (x, y) DO NOTHING RETURNING id, player_id, name, x, y, state, population, meta""",
        player_id, name, x, y, state, now,
    )
    if r is None:
        return None
    v = VillageRow.from_record(r)
    await game.emit("ovian_village_founded", game=game, tx=tx, village=v)
    await save_village(game, tx, v)
    tx.publish(game.topics.map, {"type": "map.village_founded", "at": now, "data": v.public()})
    return v


class Register(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=200)
    tribe: str


class Login(BaseModel):
    username: str
    password: str


async def record_login(game: Game, conn: asyncpg.Connection, player_id: int) -> None:
    """Count the login, and grant superuser rights to names listed in OVIAN_ADMIN_USERS."""
    now = game.clock.now()
    admins = [u.lower() for u in Settings.split(game.settings.admin_users)]
    bots = [u.lower() for u in Settings.split(game.settings.bot_users)]
    await conn.execute(
        """UPDATE players SET last_login_at = $2, last_seen_at = $2, logins = logins + 1,
                  is_admin = is_admin OR lower(username) = ANY($3::text[]), bot = bot OR lower(username) = ANY($4::text[]) WHERE id = $1""",
        player_id, now, admins, bots,
    )


def token_response(game: Game, player: dict[str, Any]) -> dict[str, Any]:
    s = game.settings
    return {
        "token": issue_token(s.jwt_secret, player["id"], player["username"], s.world_id, s.jwt_ttl_hours),
        "player": {"id": player["id"], "username": player["username"], "tribe": player["tribe"]},
    }


@router.post("/auth/register", status_code=201)
async def register(body: Register, game: GameDep) -> dict[str, Any]:
    if not USERNAME.match(body.username):
        raise GameError(422, "invalid_username", "3-24 letters, digits, _ or -")
    if body.tribe not in game.content.tribe_ids():
        raise GameError(422, "unknown_tribe")
    password_hash = await hash_password(body.password)
    try:
        async with game.tx() as tx:
            player_id = await tx.conn.fetchval(
                "INSERT INTO players(username, password_hash, tribe, created_at) VALUES ($1, $2, $3, $4) RETURNING id",
                body.username, password_hash, body.tribe, game.clock.now(),
            )
            village = await found_village(game, tx, player_id, f"{body.username}'s village")
            await record_login(game, tx.conn, player_id)
            player = await get_player(tx.conn, player_id)
            await game.emit("ovian_player_registered", game=game, tx=tx, player=player)
    except asyncpg.UniqueViolationError as e:
        raise rule("username_taken") from e
    return token_response(game, player) | {"village_id": village.id}


@router.post("/auth/login")
async def login(body: Login, game: GameDep) -> dict[str, Any]:
    assert game.pool is not None
    r = await game.pool.fetchrow(
        "SELECT id, username, tribe, password_hash FROM players WHERE lower(username) = lower($1)", body.username
    )
    if r is None or not await verify_password(body.password, r["password_hash"]):
        raise GameError(401, "invalid_credentials")
    from .rounds import check_ban

    check_ban(game, r["id"])
    await record_login(game, game.pool, r["id"])
    return token_response(game, dict(r))


@router.get("/me")
async def me(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    assert game.pool is not None
    async with game.pool.acquire() as conn:
        player = await get_player(conn, player_id)
        villages = await conn.fetch(
            "SELECT id, name, x, y, population FROM villages WHERE player_id = $1 ORDER BY id", player_id
        )
        unread = await conn.fetchval("SELECT count(*) FROM reports WHERE player_id = $1 AND NOT read", player_id)
        is_admin, vacation_until, bot, pmeta = await conn.fetchrow("SELECT is_admin, vacation_until, bot, meta FROM players WHERE id = $1", player_id)
    return {
        "id": player["id"],
        "username": player["username"],
        "tribe": player["tribe"],
        "protected_until": player["protected_until"],
        "villages": [dict(v) for v in villages],
        "unread_reports": unread,
        "is_admin": is_admin,
        "vacation_until": vacation_until,
        "bot": bot,
        "tutorial": not pmeta.get("tutorial_off", False),
        "former_names": pmeta.get("former_names", []),
        "rename_ready_at": (pmeta["renamed_at"] + int(game.settings.rename_days * 86_400_000)) if pmeta.get("renamed_at") else None,
    }


class NewName(BaseModel):
    username: str
    password: str


@router.post("/me/username")
async def change_username(body: NewName, request: Request, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Take a new name. Needs the password; once every ``OVIAN_RENAME_DAYS`` days. Cities still
    called "<old name>'s village" follow the new name. Returns a fresh token."""
    require_session(request)
    new = body.username.strip()
    if not USERNAME.match(new):
        raise GameError(422, "invalid_username", "3-24 letters, digits, _ or -")
    reserved = {u.lower() for u in Settings.split(game.settings.admin_users) + Settings.split(game.settings.bot_users)}
    now = game.clock.now()
    try:
        async with game.tx() as tx:
            p = await tx.conn.fetchrow("SELECT id, username, tribe, password_hash, bot, meta FROM players WHERE id = $1 FOR UPDATE", player_id)
            if p["bot"]:
                raise rule("bots_keep_their_name")
            if not await verify_password(body.password, p["password_hash"]):
                raise GameError(401, "invalid_credentials", "wrong password")
            old = p["username"]
            if new == old:
                raise rule("same_name", "that is already your name")
            if new.lower() != old.lower() and new.lower() in reserved:
                raise rule("username_taken")
            meta = p["meta"] or {}
            last = meta.get("renamed_at", 0)
            wait = int(game.settings.rename_days * 86_400_000)
            if last and now - last < wait:
                raise rule("rename_too_soon", f"you can change your name again in {(last + wait - now) / 3_600_000:.0f} hours")
            former = (meta.get("former_names") or []) + [old]
            await tx.conn.execute(
                "UPDATE players SET username = $2, meta = meta || $3::jsonb WHERE id = $1",
                player_id, new, {"renamed_at": now, "former_names": former[-10:]})
            rows = await tx.conn.fetch("UPDATE villages SET name = $3 WHERE player_id = $1 AND name = $2 RETURNING id",
                                       player_id, f"{old}'s village", f"{new}'s village")
            for r in rows:
                v = await get_village(tx.conn, r["id"])
                await save_village(game, tx, v)
                tx.publish(game.topics.map, {"type": "map.village_changed", "at": now, "data": v.public()})
            if game.content.extensions.get("chronicle"):
                from .chronicle import record

                await record(game, tx, "renamed", f"{old} is now known as {new}", player_id=player_id, data={"from": old, "to": new})
    except asyncpg.UniqueViolationError as e:
        raise rule("username_taken") from e
    return token_response(game, {"id": player_id, "username": new, "tribe": p["tribe"]}) | {"renamed_at": now}


class DeleteAccount(BaseModel):
    password: str
    #: The username again, as a guard against a slip.
    confirm: str


@router.post("/me/delete")
async def delete_account(body: DeleteAccount, request: Request, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Delete your account for good: your cities leave the map, with everything in them.

    Other players lose nothing they own: cities you held as vassals go free, your vassals' and
    allies' troops stationed in your cities and armies marching on them go home, and a leader's
    alliance passes to the next member. Reports, chat, messages and achievements go with the account;
    the chronicle keeps its entries. Needs the password and the username."""
    require_session(request)
    from .military import add_units
    from .submission import release

    async with game.tx() as tx:
        p = await tx.conn.fetchrow("SELECT id, username, password_hash, bot FROM players WHERE id = $1 FOR UPDATE", player_id)
        if p is None:
            raise GameError(404, "player_not_found")
        if p["bot"]:
            raise rule("bots_stay", "AI rulers are removed by the administrator")
        if not await verify_password(body.password, p["password_hash"]):
            raise GameError(401, "invalid_credentials", "wrong password")
        if body.confirm.strip().lower() != p["username"].lower():
            raise rule("confirm_username", "type your username to confirm")
        mine = [r["id"] for r in await tx.conn.fetch("SELECT id FROM villages WHERE player_id = $1 ORDER BY id", player_id)]
        # vassal ties both ways: overlords stop counting on tribute, vassals go free
        ties = await tx.conn.fetch(
            "SELECT vassal_id FROM vassals WHERE (vassal_id = ANY($1::bigint[]) OR overlord_id = ANY($1::bigint[])) ORDER BY vassal_id", mine)
        for t in ties:
            v = await get_village(tx.conn, t["vassal_id"], lock=True)
            await release(game, tx, v, reason="abandoned")
        # other players' troops in my cities, or marching on them, are home at once
        back: dict[int, dict[str, Any]] = {}
        for s in await tx.conn.fetch("SELECT home_id, units FROM stationed WHERE host_id = ANY($1::bigint[]) AND NOT home_id = ANY($1::bigint[])", mine):
            b = back.setdefault(s["home_id"], {"units": {}, "loot": {}})
            b["units"] = add_units(b["units"], s["units"])
        moving = await tx.conn.fetch(
            "SELECT id, home_id, units, loot FROM movements WHERE (to_id = ANY($1::bigint[]) OR from_id = ANY($1::bigint[])) AND NOT home_id = ANY($1::bigint[])", mine)
        for m in moving:
            b = back.setdefault(m["home_id"], {"units": {}, "loot": {}})
            b["units"] = add_units(b["units"], m["units"])
            for r, n in (m["loot"] or {}).items():
                b["loot"][r] = b["loot"].get(r, 0) + n
            await tx.conn.execute("DELETE FROM jobs WHERE kind = 'movement.arrive' AND (payload->>'movement_id')::bigint = $1", m["id"])
        from ..repo import accrue
        from .villages import push_village

        for home_id, b in sorted(back.items()):
            home = await get_village(tx.conn, home_id, lock=True)
            await accrue(game, tx, home)
            home.state["units"] = add_units(home.state.get("units", {}), b["units"])
            if b["loot"]:
                home.state = game.engine.deposit(home.state, b["loot"])
            await save_village(game, tx, home)
            game.event(tx, home.player_id, "movement.returned", {"village_id": home.id, "units": b["units"], "loot": b["loot"], "hero": False})
            await push_village(game, tx, home)
        member = await tx.conn.fetchrow("SELECT alliance_id FROM alliance_members WHERE player_id = $1", player_id)
        if member:
            from .alliances import _remove

            await _remove(game, tx, member["alliance_id"], player_id, "deleted")
        if game.content.extensions.get("chronicle"):
            from .chronicle import record

            await record(game, tx, "departed", f"{p['username']} left the world", player_id=player_id, data={"cities": len(mine)})
        await tx.conn.execute("DELETE FROM jobs WHERE village_id = ANY($1::bigint[]) OR (payload->>'player_id')::bigint = $2", mine, player_id)
        await tx.conn.execute("DELETE FROM players WHERE id = $1", player_id)
        now = game.clock.now()
        for vid in mine:
            tx.publish(game.topics.map, {"type": "map.village_removed", "at": now, "data": {"id": vid}})
    return {"deleted": True}


@router.post("/me/heartbeat", status_code=204)
async def heartbeat(player_id: PlayerId) -> None:
    """Clients call this every minute or so while open; it marks the player online."""
    # current_player_id already recorded the visit.


@router.get("/realtime")
async def realtime_info(player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """How to connect to the MQTT broker: username is your player id, password is your API token."""
    t = game.topics
    return {
        "url": game.settings.mqtt_public_url,
        "username": str(player_id),
        "password": "<your bearer token>",
        "topics": {
            "events": t.player(player_id),
            "map": t.map,
            "server": t.server,
            "chat": t.chat("{channel}"),
            "chat_post": t.chat_in("{channel}", player_id),
        },
    }


module = Module("auth", router=router)
