"""Players from the hub: one account, many worlds (docs/worlds.md).

The hub hands a logged-in account a short-lived *ticket* for this world, signed with ``OVIAN_HUB_SECRET``.

- ``POST /auth/hub {ticket, tribe?, username?}``: log in the account's player here, or found it (needs a tribe).
  A local player of the same name that is not linked yet answers ``link_required``: its owner proves it with
  ``POST /auth/hub/link {ticket, password}``; anyone else picks another ``username``.
- ``POST /internal/hub/profile`` (header ``X-Hub-Key``): the hub pushes new badges or founder status.
- ``POST /internal/hub/name`` and ``/internal/hub/claim`` (header ``X-Hub-Key``): the hub asks whether a name belongs
  to a player here, and lets a player who lived here before the hub log into the hub with this world's password
  (their hub account is created and linked on the spot).

Players from the hub have no password here; they rename on the hub, not in a world.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from typing import TYPE_CHECKING, Any

import asyncpg
import httpx
import jwt
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import GameError, rule
from ..repo import get_player
from ..security import verify_password
from .base import Module

if TYPE_CHECKING:
    from ..game import Game

log = logging.getLogger("ovian.hub")
router = APIRouter(tags=["auth"])
NO_PASSWORD = "!hub"
_tasks: set[asyncio.Task[Any]] = set()


def badges_of(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """What a world keeps of a badge: enough to draw it."""
    return [{k: b.get(k) for k in ("id", "name", "icon", "color", "kind")} for b in profile.get("badges", [])][:12]


def read_ticket(game: Game, ticket: str) -> dict[str, Any]:
    secret = game.settings.hub_secret
    if not secret:
        raise GameError(404, "no_hub", "this world has no hub")
    try:
        claims = jwt.decode(ticket, secret, algorithms=["HS256"], audience="ovian-world", options={"require": ["sub", "exp", "world"]})
    except jwt.PyJWTError as e:
        raise GameError(401, "invalid_ticket", str(e)) from e
    if claims["world"] != game.settings.world_id:
        raise GameError(401, "invalid_ticket", "ticket is for another world")
    return claims


async def apply_profile(conn: Any, player_id: int, profile: dict[str, Any]) -> None:
    await conn.execute("UPDATE players SET badges = $2, founder_no = $3 WHERE id = $1",
                       player_id, badges_of(profile), profile.get("founder_no") if profile.get("founder") else None)


def _to_hub(game: Game, method: str, path: str, body: dict[str, Any] | None = None) -> None:
    """Best-effort call to the hub's internal API, in the background."""
    if not game.settings.hub_url:
        return

    async def send() -> None:
        url = f"{game.settings.hub_url.rstrip('/')}/api/v1/internal/worlds/{game.settings.world_id}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.request(method, url, json=body, headers={"X-Hub-Key": game.settings.hub_secret})
                r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("could not reach the hub (%s %s): %s", method, path, e)

    t = asyncio.create_task(send())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def tell_hub(game: Game, account_id: int, player_id: int) -> None:
    """Report a member to the hub, so it lists the world as joined and pushes badge changes here."""
    _to_hub(game, "POST", "/members", {"account_id": account_id, "player_id": player_id})


def tell_hub_left(game: Game, account_id: int) -> None:
    _to_hub(game, "DELETE", f"/members/{account_id}")


async def _enter(game: Game, player_id: int, claims: dict[str, Any]) -> dict[str, Any]:
    from .auth import record_login, token_response
    from .rounds import check_ban

    assert game.pool is not None
    check_ban(game, player_id)
    async with game.pool.acquire() as conn:
        await apply_profile(conn, player_id, claims.get("profile", {}))
        await record_login(game, conn, player_id)
        player = await get_player(conn, player_id)
        village_id = await conn.fetchval("SELECT min(id) FROM villages WHERE player_id = $1", player_id)
    tell_hub(game, int(claims["sub"]), player_id)
    return token_response(game, player) | {"village_id": village_id}


class HubLogin(BaseModel):
    ticket: str
    tribe: str | None = None
    #: A name for this world, when the account's own is taken here.
    username: str | None = Field(default=None, min_length=3, max_length=24)


@router.post("/auth/hub")
async def hub_login(body: HubLogin, game: GameDep) -> dict[str, Any]:
    from .auth import USERNAME, found_village, record_login

    claims = read_ticket(game, body.ticket)
    account_id = int(claims["sub"])
    assert game.pool is not None
    player_id = await game.pool.fetchval("SELECT id FROM players WHERE account_id = $1", account_id)
    if player_id is not None:
        return await _enter(game, player_id, claims) | {"joined": False}

    name = (body.username or claims["name"]).strip()
    if not USERNAME.match(name):
        raise GameError(422, "invalid_username", "3-24 letters, digits, _ or -")
    local = await game.pool.fetchrow("SELECT id, account_id, bot FROM players WHERE lower(username) = lower($1)", name)
    if local is not None:
        if local["account_id"] is None and not local["bot"] and name.lower() == claims["name"].lower():
            raise rule("link_required", "a player of this name already lives here: give its password to link it, or choose another name")
        raise rule("username_taken")
    if not body.tribe:
        raise rule("tribe_required", "choose a people to found your first city")
    if body.tribe not in game.content.tribe_ids():
        raise GameError(422, "unknown_tribe")
    try:
        async with game.tx() as tx:
            player_id = await tx.conn.fetchval(
                "INSERT INTO players(username, password_hash, tribe, created_at, account_id) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                name, NO_PASSWORD, body.tribe, game.clock.now(), account_id)
            await found_village(game, tx, player_id, f"{name}'s village")
            await record_login(game, tx.conn, player_id)
            player = await get_player(tx.conn, player_id)
            await game.emit("ovian_player_registered", game=game, tx=tx, player=player)
    except asyncpg.UniqueViolationError as e:
        raise rule("username_taken") from e
    return await _enter(game, player_id, claims) | {"joined": True}


class HubLink(BaseModel):
    ticket: str
    password: str
    #: The local player's name, if it differs from the account's.
    username: str | None = None


@router.post("/auth/hub/link")
async def hub_link(body: HubLink, game: GameDep) -> dict[str, Any]:
    """Join a player that already lives in this world to the hub account (one time, with its password)."""
    claims = read_ticket(game, body.ticket)
    account_id = int(claims["sub"])
    assert game.pool is not None
    if await game.pool.fetchval("SELECT 1 FROM players WHERE account_id = $1", account_id):
        raise rule("already_linked", "this account already has a player here")
    r = await game.pool.fetchrow("SELECT id, account_id, password_hash, bot FROM players WHERE lower(username) = lower($1)",
                                 body.username or claims["name"])
    if r is None or r["bot"] or not await verify_password(body.password, r["password_hash"]):
        raise GameError(401, "invalid_credentials")
    if r["account_id"] is not None:
        raise rule("already_linked", "this player belongs to another account")
    await game.pool.execute("UPDATE players SET account_id = $2 WHERE id = $1", r["id"], account_id)
    return await _enter(game, r["id"], claims) | {"joined": False, "linked": True}


class Profile(BaseModel):
    account_id: int
    founder: bool = False
    founder_no: int | None = None
    badges: list[dict[str, Any]] = []


@router.post("/internal/hub/profile", include_in_schema=False)
async def hub_profile(body: Profile, game: GameDep, x_hub_key: str = Header("")) -> dict[str, Any]:
    _check_key(game, x_hub_key)
    assert game.pool is not None
    player_id = await game.pool.fetchval("SELECT id FROM players WHERE account_id = $1", body.account_id)
    if player_id is None:
        return {"ok": False, "player_id": None}
    await apply_profile(game.pool, player_id, body.model_dump())
    game.realtime.publish(game.topics.player(player_id), {"type": "player.badges", "at": game.clock.now(),
                                                         "data": {"badges": badges_of(body.model_dump()), "founder_no": body.founder_no}})
    return {"ok": True, "player_id": player_id}


def _check_key(game: Game, key: str) -> None:
    if not game.settings.hub_secret or not hmac.compare_digest(key, game.settings.hub_secret):
        raise GameError(401, "invalid_key")


class NameQuery(BaseModel):
    username: str


@router.post("/internal/hub/name", include_in_schema=False)
async def hub_name(body: NameQuery, game: GameDep, x_hub_key: str = Header("")) -> dict[str, Any]:
    """Does a player who is not on the hub yet live here under this name? Then only its owner may take it there."""
    _check_key(game, x_hub_key)
    assert game.pool is not None
    taken = await game.pool.fetchval(
        "SELECT 1 FROM players WHERE lower(username) = lower($1) AND account_id IS NULL AND NOT bot", body.username)
    return {"taken": bool(taken)}


class Claim(BaseModel):
    username: str
    password: str
    #: Link the player to this hub account; without it, only check the password.
    account_id: int | None = None


@router.post("/internal/hub/claim", include_in_schema=False)
async def hub_claim(body: Claim, game: GameDep, x_hub_key: str = Header("")) -> dict[str, Any]:
    """The hub logs in a player of this world who has no hub account yet, with this world's password."""
    _check_key(game, x_hub_key)
    assert game.pool is not None
    r = await game.pool.fetchrow(
        "SELECT id, username, password_hash FROM players WHERE lower(username) = lower($1) AND account_id IS NULL AND NOT bot",
        body.username)
    if r is None or r["password_hash"] == NO_PASSWORD or not await verify_password(body.password, r["password_hash"]):
        return {"ok": False}
    if body.account_id is not None:
        done = await game.pool.execute("UPDATE players SET account_id = $2 WHERE id = $1 AND account_id IS NULL", r["id"], body.account_id)
        if done != "UPDATE 1":
            return {"ok": False}
    return {"ok": True, "player_id": r["id"], "username": r["username"]}


module = Module("hub", router=router)
