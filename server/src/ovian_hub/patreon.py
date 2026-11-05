"""Patreon: link an account with OAuth, keep its pledge current with the webhook, and turn tiers into badges.

Patrons get badges, and early access to worlds that allow it; nothing that changes the game's balance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import RedirectResponse

from ovian_server.errors import GameError, rule

from .hub import AccountId, Hub, HubDep

log = logging.getLogger("ovian.hub.patreon")
router = APIRouter(tags=["patreon"])
AUTHORIZE = "https://www.patreon.com/oauth2/authorize"
TOKEN = "https://www.patreon.com/api/oauth2/token"
IDENTITY = "https://www.patreon.com/api/oauth2/v2/identity"


def _enabled(hub: Hub) -> None:
    if not hub.settings.patreon_client_id:
        raise GameError(503, "patreon_disabled", "Patreon is not configured on this hub")


def redirect_uri(hub: Hub) -> str:
    return hub.settings.public_api_url.rstrip("/") + "/api/v1/patreon/callback"


def membership(identity: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    """The pledge in a Patreon identity document (``include=memberships...``): status, tiers and amount."""
    best = {"patron_status": None, "tier_ids": [], "cents": 0}
    for item in identity.get("included", []):
        if item.get("type") != "member":
            continue
        rel = item.get("relationships", {})
        campaign = ((rel.get("campaign") or {}).get("data") or {}).get("id")
        if campaign_id and campaign != campaign_id:
            continue
        attrs = item.get("attributes", {})
        tiers = [t["id"] for t in ((rel.get("currently_entitled_tiers") or {}).get("data") or [])]
        m = {"patron_status": attrs.get("patron_status"), "tier_ids": tiers,
             "cents": int(attrs.get("currently_entitled_amount_cents") or 0)}
        if m["patron_status"] == "active_patron" or best["patron_status"] is None:
            best = m
    return best


async def sync_badges(hub: Hub, conn: Any, account_id: int) -> bool:
    """Patron badges follow the pledge: give the ones its tiers earn, take back the others. True if anything changed."""
    link = await conn.fetchrow("SELECT patron_status, tier_ids FROM patreon_links WHERE account_id = $1", account_id)
    earned: set[str] = set()
    if link and link["patron_status"] == "active_patron":
        tiers = set(link["tier_ids"])
        for b in await conn.fetch("SELECT id, patreon_tier FROM badges WHERE kind = 'patron'"):
            if b["patreon_tier"] == "*" or b["patreon_tier"] in tiers:
                earned.add(b["id"])
    have = {r["badge_id"] for r in await conn.fetch(
        "SELECT badge_id FROM account_badges WHERE account_id = $1 AND source = 'patreon'", account_id)}
    for b in have - earned:
        await conn.execute("DELETE FROM account_badges WHERE account_id = $1 AND badge_id = $2 AND source = 'patreon'", account_id, b)
    for b in earned - have:
        await conn.execute(
            """INSERT INTO account_badges(account_id, badge_id, source, granted_at) VALUES ($1, $2, 'patreon', $3)
               ON CONFLICT (account_id, badge_id) DO NOTHING""", account_id, b, hub.now())
    return have != earned


async def sync_all(hub: Hub) -> None:
    assert hub.pool is not None
    for r in await hub.pool.fetch("SELECT account_id FROM patreon_links"):
        if await sync_badges(hub, hub.pool, r["account_id"]):
            await hub.push_profile(r["account_id"])


async def link(hub: Hub, account_id: int, patreon_user_id: str, m: dict[str, Any]) -> None:
    assert hub.pool is not None
    now = hub.now()
    async with hub.pool.acquire() as conn, conn.transaction():
        other = await conn.fetchval("SELECT account_id FROM patreon_links WHERE patreon_user_id = $1", patreon_user_id)
        if other is not None and other != account_id:
            raise rule("patreon_taken", "this Patreon account is linked to another player")
        await conn.execute(
            """INSERT INTO patreon_links(account_id, patreon_user_id, patron_status, tier_ids, cents, linked_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $6)
               ON CONFLICT (account_id) DO UPDATE SET patreon_user_id = $2, patron_status = $3, tier_ids = $4, cents = $5, updated_at = $6""",
            account_id, patreon_user_id, m["patron_status"], m["tier_ids"], m["cents"], now)
        await sync_badges(hub, conn, account_id)
    await hub.push_profile(account_id)


@router.get("/patreon/connect")
async def connect(account_id: AccountId, hub: HubDep) -> dict[str, Any]:
    """Where to send the player to link Patreon. Patreon sends them back to /patreon/callback."""
    _enabled(hub)
    q = {"response_type": "code", "client_id": hub.settings.patreon_client_id, "redirect_uri": redirect_uri(hub),
         "scope": "identity identity.memberships", "state": hub.state_token(account_id)}
    return {"url": f"{AUTHORIZE}?{urlencode(q)}"}


async def fetch_identity(hub: Hub, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TOKEN, data={
            "code": code, "grant_type": "authorization_code", "client_id": hub.settings.patreon_client_id,
            "client_secret": hub.settings.patreon_client_secret, "redirect_uri": redirect_uri(hub)})
        r.raise_for_status()
        access = r.json()["access_token"]
        r = await c.get(IDENTITY, headers={"Authorization": f"Bearer {access}"}, params={
            "include": "memberships,memberships.currently_entitled_tiers,memberships.campaign",
            "fields[member]": "patron_status,currently_entitled_amount_cents",
            "fields[user]": "full_name"})
        r.raise_for_status()
        return r.json()


@router.get("/patreon/callback", include_in_schema=False)
async def callback(hub: HubDep, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    back = hub.settings.public_url.rstrip("/") + "/?patreon="
    if error or not code:
        return RedirectResponse(back + "cancelled", status_code=303)
    account_id = hub.state_account(state)
    try:
        identity = await (hub.patreon_identity or fetch_identity)(hub, code)
        await link(hub, account_id, str(identity["data"]["id"]), membership(identity, hub.settings.patreon_campaign_id))
    except GameError as e:
        return RedirectResponse(back + e.code, status_code=303)
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("patreon link failed: %s", e)
        return RedirectResponse(back + "error", status_code=303)
    return RedirectResponse(back + "linked", status_code=303)


@router.delete("/me/patreon")
async def unlink(account_id: AccountId, hub: HubDep) -> dict[str, Any]:
    async with hub.pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM patreon_links WHERE account_id = $1", account_id)
        await sync_badges(hub, conn, account_id)
    await hub.push_profile(account_id)
    return {"ok": True}


def verify(secret: str, body: bytes, signature: str) -> bool:
    """Patreon signs webhook bodies with HMAC-MD5 of the webhook secret, hex encoded."""
    want = hmac.new(secret.encode(), body, hashlib.md5).hexdigest()
    return bool(secret) and hmac.compare_digest(want, signature or "")


@router.post("/patreon/webhook", include_in_schema=False)
async def webhook(request: Request, hub: HubDep, x_patreon_signature: str = Header(""), x_patreon_event: str = Header("")) -> dict[str, Any]:
    """members:create/update/delete and members:pledge:*: keeps pledges current, also for patrons not linked yet."""
    body = await request.body()
    if not verify(hub.settings.patreon_webhook_secret, body, x_patreon_signature):
        raise GameError(401, "invalid_signature")
    doc = json.loads(body)
    data = doc.get("data") or {}
    rel = data.get("relationships", {})
    user_id = ((rel.get("user") or {}).get("data") or {}).get("id")
    if not user_id:
        return {"ignored": True}
    campaign = ((rel.get("campaign") or {}).get("data") or {}).get("id")
    if hub.settings.patreon_campaign_id and campaign and campaign != hub.settings.patreon_campaign_id:
        return {"ignored": True}
    attrs = data.get("attributes", {})
    deleted = x_patreon_event.endswith(":delete")
    m = {"patron_status": None if deleted else attrs.get("patron_status"),
         "tier_ids": [] if deleted else [t["id"] for t in ((rel.get("currently_entitled_tiers") or {}).get("data") or [])],
         "cents": 0 if deleted else int(attrs.get("currently_entitled_amount_cents") or 0)}
    now = hub.now()
    async with hub.pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO patreon_members(patreon_user_id, patron_status, tier_ids, cents, updated_at) VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (patreon_user_id) DO UPDATE SET patron_status = $2, tier_ids = $3, cents = $4, updated_at = $5""",
            str(user_id), m["patron_status"], m["tier_ids"], m["cents"], now)
        account_id = await conn.fetchval(
            """UPDATE patreon_links SET patron_status = $2, tier_ids = $3, cents = $4, updated_at = $5
               WHERE patreon_user_id = $1 RETURNING account_id""",
            str(user_id), m["patron_status"], m["tier_ids"], m["cents"], now)
        changed = account_id is not None and await sync_badges(hub, conn, account_id)
    if changed:
        await hub.push_profile(account_id)
    return {"ok": True, "account_id": account_id}
