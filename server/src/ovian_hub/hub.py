"""Shared state of the hub process, tokens, and the helpers the routes use."""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from typing import Annotated, Any, Callable

import asyncpg
import httpx
import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ovian_server.errors import GameError

from .config import HubSettings

log = logging.getLogger("ovian.hub")
TICKET_AUDIENCE = "ovian-world"


class Hub:
    def __init__(self, settings: HubSettings, now: Callable[[], int] | None = None):
        self.settings = settings
        self.pool: asyncpg.Pool | None = None
        self.now = now or (lambda: int(time.time() * 1000))
        #: replaced in tests; posts JSON to a world's internal endpoint
        self.post: Callable[[str, dict[str, Any], dict[str, str]], Any] = self._post
        #: replaced in tests; posts JSON to a world's internal endpoint and returns its JSON answer
        self.ask: Callable[[str, dict[str, Any], dict[str, str]], Any] = self._ask
        self.tasks: set[asyncio.Task[Any]] = set()
        #: replaced in tests; exchanges a Patreon OAuth code for the identity document
        self.patreon_identity: Callable[[Hub, str], Any] | None = None

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json=body, headers=headers)
            r.raise_for_status()

    async def _ask(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

    async def ask_worlds(self, path: str, body: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Ask every live world (in list order) at ``/api/v1/internal/hub/<path>``; a world that is down is skipped."""
        assert self.pool is not None
        rows = await self.pool.fetch("SELECT id, internal_url FROM worlds WHERE internal_url <> '' AND status <> 'ended' ORDER BY sort, id")
        out = []
        for r in rows:
            url = r["internal_url"].rstrip("/") + "/api/v1/internal/hub/" + path
            try:
                out.append((r["id"], await self.ask(url, body, {"X-Hub-Key": self.settings.world_secret})))
            except Exception as e:  # noqa: BLE001 - a world being down must not fail the hub
                log.warning("could not ask world %s (%s): %s", r["id"], path, e)
        return out

    def background(self, coro: Any) -> None:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    # ---- tokens ----

    def login_token(self, account_id: int, username: str) -> str:
        now = int(time.time())
        claims = {"sub": str(account_id), "name": username, "aud": "ovian-hub", "iat": now,
                  "exp": now + self.settings.jwt_ttl_hours * 3600}
        return jwt.encode(claims, self.settings.jwt_secret, algorithm="HS256")

    def account_of(self, token: str) -> int:
        try:
            claims = jwt.decode(token, self.settings.jwt_secret, algorithms=["HS256"], audience="ovian-hub",
                                options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as e:
            raise GameError(401, "invalid_token", str(e)) from e
        return int(claims["sub"])

    def ticket(self, world_id: str, profile: dict[str, Any]) -> str:
        """A short-lived pass into one world, signed with the secret the worlds share with the hub."""
        now = int(time.time())
        claims = {"sub": str(profile["account_id"]), "name": profile["username"], "world": world_id,
                  "aud": TICKET_AUDIENCE, "iat": now, "exp": now + self.settings.ticket_ttl_seconds,
                  "profile": profile}
        return jwt.encode(claims, self.settings.world_secret, algorithm="HS256")

    def state_token(self, account_id: int) -> str:
        now = int(time.time())
        return jwt.encode({"sub": str(account_id), "aud": "patreon-state", "exp": now + 900},
                          self.settings.jwt_secret, algorithm="HS256")

    def state_account(self, state: str) -> int:
        try:
            return int(jwt.decode(state, self.settings.jwt_secret, algorithms=["HS256"], audience="patreon-state")["sub"])
        except jwt.PyJWTError as e:
            raise GameError(400, "invalid_state", str(e)) from e

    # ---- profiles and badges ----

    async def profile(self, conn: asyncpg.Connection | asyncpg.Pool, account_id: int) -> dict[str, Any]:
        """What a world shows about an account: name, founder number, badges, patron."""
        a = await conn.fetchrow("SELECT id, username, founder, founder_no FROM accounts WHERE id = $1", account_id)
        if a is None:
            raise GameError(404, "account_not_found")
        badges = await conn.fetch(
            """SELECT b.id, b.name, b.icon, b.color, b.kind, b.description FROM account_badges ab
               JOIN badges b ON b.id = ab.badge_id WHERE ab.account_id = $1 ORDER BY b.sort, b.name""", account_id)
        patron = await conn.fetchval(
            "SELECT patron_status = 'active_patron' FROM patreon_links WHERE account_id = $1", account_id)
        return {"account_id": a["id"], "username": a["username"], "founder": a["founder"],
                "founder_no": a["founder_no"], "patron": bool(patron), "badges": [dict(b) for b in badges]}

    async def push_profile(self, account_id: int) -> None:
        """Tell every world the account plays in about its new badges (best effort; worlds also learn at login)."""
        assert self.pool is not None
        rows = await self.pool.fetch(
            """SELECT w.id, w.internal_url FROM memberships m JOIN worlds w ON w.id = m.world_id
               WHERE m.account_id = $1 AND w.internal_url <> '' AND w.status <> 'ended'""", account_id)
        if not rows:
            return
        profile = await self.profile(self.pool, account_id)

        async def send() -> None:
            for r in rows:
                url = r["internal_url"].rstrip("/") + "/api/v1/internal/hub/profile"
                try:
                    await self.post(url, profile, {"X-Hub-Key": self.settings.world_secret})
                except Exception as e:  # noqa: BLE001 - a world being down must not fail the hub
                    log.warning("could not update world %s: %s", r["id"], e)

        self.background(send())


_bearer = HTTPBearer(auto_error=False)


def get_hub(request: Request) -> Hub:
    return request.app.state.hub


HubDep = Annotated[Hub, Depends(get_hub)]


async def current_account(hub: HubDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> int:
    if creds is None:
        raise GameError(401, "unauthorized", "missing bearer token")
    return hub.account_of(creds.credentials)


AccountId = Annotated[int, Depends(current_account)]


async def current_admin(hub: HubDep, account_id: AccountId) -> int:
    assert hub.pool is not None
    if not await hub.pool.fetchval("SELECT is_admin FROM accounts WHERE id = $1", account_id):
        raise GameError(403, "admin_only")
    return account_id


AdminId = Annotated[int, Depends(current_admin)]


def require_world_key(hub: HubDep, x_hub_key: Annotated[str, Header()] = "") -> None:
    if not hmac.compare_digest(x_hub_key, hub.settings.world_secret):
        raise GameError(401, "invalid_key")
