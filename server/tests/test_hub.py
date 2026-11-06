"""The hub: shared accounts, founders and badges, Patreon, worlds, and tickets into a world."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, AsyncIterator

import httpx
import pytest
import pytest_asyncio

from ovian_hub.app import create_app
from ovian_hub.config import HubSettings
from ovian_hub.hub import Hub

SECRET = "test-world-secret-long-enough-for-hs256"
HUB_TABLES = "accounts, badges, account_badges, patreon_links, patreon_members, worlds, memberships"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def hub_app(settings) -> AsyncIterator[Any]:
    hs = HubSettings(database_url=settings.database_url, jwt_secret="hub-test-secret-long-enough-for-hs256",
                     world_secret=SECRET, admin_users="boss", public_url="https://play.test",
                     public_api_url="https://play.test/hub", patreon_client_id="cid", patreon_client_secret="cs",
                     patreon_webhook_secret="whs", patreon_campaign_id="camp")
    hub = Hub(hs)
    app = create_app(hs, hub)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def hub(hub_app, game, monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    h: Hub = hub_app.state.hub
    await h.pool.execute(f"TRUNCATE {HUB_TABLES} RESTART IDENTITY CASCADE")
    await h.pool.execute(
        """INSERT INTO badges(id, name, description, icon, color, kind, patreon_tier, sort, created_at) VALUES
           ('founder', 'Founder', '', '🏛', '#c9962e', 'founder', NULL, 0, 0), ('patron', 'Patron', '', '🏺', '#9b4d2e', 'patron', '*', 10, 0)""")
    h.pushed = []

    async def post(url: str, body: dict[str, Any], headers: dict[str, str]) -> None:
        h.pushed.append((url, body))

    h.post = post

    async def unreachable(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        raise httpx.ConnectError("no world in this test")

    h.ask = unreachable
    monkeypatch.setattr(game.settings, "hub_secret", SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hub_app), base_url="http://hub/api/v1") as c:
        c.hub = h  # type: ignore[attr-defined]
        await h.pool.execute(
            "INSERT INTO worlds(id, name, api_url, internal_url, created_at) VALUES ('w1', 'Test world', '/w/w1', 'http://w1:8000', 0)")
        yield c


async def account(hub: httpx.AsyncClient, name: str) -> dict[str, str]:
    r = await hub.post("/auth/register", json={"username": name, "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def ticket(hub: httpx.AsyncClient, auth: dict[str, str], world: str = "w1") -> str:
    r = await hub.post(f"/worlds/{world}/ticket", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


async def test_one_account_enters_a_world_with_its_badges(hub, client, game) -> None:
    boss = await account(hub, "boss")
    ann = await account(hub, "ann")
    ann_id = (await hub.get("/me", headers=ann)).json()["account_id"]

    # founders: number given in order, founder badge comes with it
    r = await hub.post(f"/admin/accounts/{ann_id}/founder", json={"founder": True}, headers=boss)
    assert r.status_code == 200, r.text
    assert r.json()["founder_no"] == 1 and [b["id"] for b in r.json()["badges"]] == ["founder"]
    assert (await hub.post(f"/admin/accounts/{ann_id}/founder", json={"founder": True}, headers=ann)).status_code == 403
    assert (await hub.get("/founders")).json()[0]["username"] == "ann"

    # into the world: needs a tribe the first time
    t = await ticket(hub, ann)
    r = await client.post("/auth/hub", json={"ticket": t})
    assert r.status_code == 409 and r.json()["error"] == "tribe_required"
    r = await client.post("/auth/hub", json={"ticket": t, "tribe": "clans"})
    assert r.status_code == 200, r.text
    assert r.json()["joined"] is True and r.json()["village_id"]
    pid = r.json()["player"]["id"]
    me = (await client.get("/me", headers={"Authorization": f"Bearer {r.json()['token']}"})).json()
    assert me["account_id"] == ann_id and me["founder_no"] == 1 and me["badges"][0]["id"] == "founder"

    # next time: the same player
    r = await client.post("/auth/hub", json={"ticket": await ticket(hub, ann)})
    assert r.json()["joined"] is False and r.json()["player"]["id"] == pid

    # badges show in the profile and the rankings
    assert (await client.get(f"/players/{pid}")).json()["badges"][0]["icon"] == "🏛"
    assert next(p for p in (await client.get("/rankings")).json() if p["id"] == pid)["founder_no"] == 1

    # a new award reaches the world through the hub's push
    await hub.put("/admin/badges/cartographer", json={"name": "Cartographer", "icon": "🗺"}, headers=boss)
    await hub.post("/internal/worlds/w1/members", json={"account_id": ann_id, "player_id": pid}, headers={"X-Hub-Key": SECRET})
    r = await hub.post(f"/admin/accounts/{ann_id}/badges/cartographer", json={}, headers=boss)
    assert {b["id"] for b in r.json()["badges"]} == {"founder", "cartographer"}
    await _drain(hub)
    url, body = hub.hub.pushed[-1]
    assert url == "http://w1:8000/api/v1/internal/hub/profile"
    assert (await client.post("/internal/hub/profile", json=body, headers={"X-Hub-Key": "nope"})).status_code == 401
    assert (await client.post("/internal/hub/profile", json=body, headers={"X-Hub-Key": SECRET})).json()["player_id"] == pid
    assert {b["id"] for b in (await client.get(f"/players/{pid}")).json()["badges"]} == {"founder", "cartographer"}

    # taking founder status back removes its badges, not the others
    r = await hub.post(f"/admin/accounts/{ann_id}/founder", json={"founder": False}, headers=boss)
    assert r.json()["founder"] is False and [b["id"] for b in r.json()["badges"]] == ["cartographer"]

    # hub players rename on the hub, and delete without a password
    tok = {"Authorization": f"Bearer {(await client.post('/auth/hub', json={'ticket': await ticket(hub, ann)})).json()['token']}"}
    r = await client.post("/me/username", json={"username": "anna", "password": "x"}, headers=tok)
    assert r.json()["error"] == "rename_on_hub"
    assert (await client.post("/me/delete", json={"confirm": "ann"}, headers=tok)).json() == {"deleted": True}


async def _drain(hub) -> None:
    import asyncio

    while hub.hub.tasks:
        await asyncio.gather(*list(hub.hub.tasks))


async def test_tickets_are_checked(hub, client, game) -> None:
    ann = await account(hub, "ann")
    # wrong secret, wrong world
    import jwt

    forged = jwt.encode({"sub": "1", "name": "ann", "world": "w1", "aud": "ovian-world", "exp": 9999999999}, "x" * 40, algorithm="HS256")
    assert (await client.post("/auth/hub", json={"ticket": forged, "tribe": "clans"})).json()["error"] == "invalid_ticket"
    await hub.hub.pool.execute("INSERT INTO worlds(id, name, api_url, created_at) VALUES ('w9', 'Other', '/w/w9', 0)")
    t = await ticket(hub, ann, "w9")
    r = await client.post("/auth/hub", json={"ticket": t, "tribe": "clans"})
    assert r.status_code == 401 and "another world" in r.json()["message"]


async def test_a_local_player_links_to_the_hub(hub, client, register) -> None:
    await register("bea")
    bea = await account(hub, "bea")
    r = await client.post("/auth/hub", json={"ticket": await ticket(hub, bea), "tribe": "clans"})
    assert r.json()["error"] == "link_required"
    assert (await client.post("/auth/hub/link", json={"ticket": await ticket(hub, bea), "password": "wrong-pass"})).status_code == 401
    r = await client.post("/auth/hub/link", json={"ticket": await ticket(hub, bea), "password": "password123"})
    assert r.status_code == 200 and r.json()["linked"] is True
    # or someone else with that name plays under another one
    other = await account(hub, "carl")
    await register("Carl")
    r = await client.post("/auth/hub", json={"ticket": await ticket(hub, other), "tribe": "clans", "username": "Carl_2"})
    assert r.status_code == 200 and r.json()["player"]["username"] == "Carl_2"


async def test_players_from_before_the_hub_log_in_with_their_world_password(hub, client, game, register) -> None:
    async def ask(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        assert url.startswith("http://w1:8000/api/v1/internal/hub/")
        r = await client.post(url.removeprefix("http://w1:8000/api/v1"), json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    hub.hub.ask = ask
    await register("Dora")
    # nobody else can take the name on the hub
    r = await hub.post("/auth/register", json={"username": "dora", "password": "password123"})
    assert r.json()["error"] == "name_in_world"
    assert (await hub.post("/auth/login", json={"username": "dora", "password": "wrong-pass"})).status_code == 401
    assert (await hub.post("/auth/login", json={"username": "nobody", "password": "password123"})).status_code == 401
    # the owner logs in with the world's password: the account is made, with the player's spelling, and linked
    r = await hub.post("/auth/login", json={"username": "dora", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["account"]["username"] == "Dora"
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    mine = {w["id"]: w for w in (await hub.get("/me/worlds", headers=auth)).json()}
    assert mine["w1"]["joined"] is True
    r = await client.post("/auth/hub", json={"ticket": await ticket(hub, auth)})
    assert r.status_code == 200 and r.json()["player"]["username"] == "Dora" and r.json()["joined"] is False
    # from now on it is a plain hub account
    assert (await hub.post("/auth/login", json={"username": "Dora", "password": "password123"})).status_code == 200
    # bad keys are refused by the world
    r = await client.post("/internal/hub/claim", json={"username": "x", "password": "y"}, headers={"X-Hub-Key": "nope"})
    assert r.status_code == 401


async def test_closed_and_early_access_worlds(hub) -> None:
    boss = await account(hub, "boss")
    ann = await account(hub, "ann")
    w = {"name": "Founders' world", "api_url": "/w/w1", "status": "open", "founders_only": True}
    assert (await hub.put("/admin/worlds/w1", json=w, headers=boss)).status_code == 200
    r = await hub.post("/worlds/w1/ticket", headers=ann)
    assert r.json()["error"] == "early_access_only"
    listed = {x["id"]: x for x in (await hub.get("/me/worlds", headers=ann)).json()}
    assert listed["w1"]["can_enter"] is False and listed["w1"]["blocked"] == "early_access_only"
    ann_id = (await hub.get("/me", headers=ann)).json()["account_id"]
    await hub.post(f"/admin/accounts/{ann_id}/founder", json={"founder": True}, headers=boss)
    assert (await hub.post("/worlds/w1/ticket", headers=ann)).status_code == 200
    await hub.put("/admin/worlds/w1", json=w | {"status": "upcoming"}, headers=boss)
    assert (await hub.post("/worlds/w1/ticket", headers=ann)).json()["error"] == "world_upcoming"


def _identity(user: str, status: str | None, tiers: list[str], campaign: str = "camp") -> dict[str, Any]:
    return {"data": {"id": user, "type": "user"}, "included": [{
        "type": "member", "id": "m1", "attributes": {"patron_status": status, "currently_entitled_amount_cents": 500},
        "relationships": {"campaign": {"data": {"id": campaign, "type": "campaign"}},
                          "currently_entitled_tiers": {"data": [{"id": t, "type": "tier"} for t in tiers]}}}]}


def _signed(body: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    return raw, hmac.new(b"whs", raw, hashlib.md5).hexdigest()


async def test_patreon_links_and_follows_the_pledge(hub) -> None:
    boss = await account(hub, "boss")
    ann = await account(hub, "ann")
    await hub.put("/admin/badges/legate", json={"name": "Legate", "kind": "patron", "patreon_tier": "t-gold"}, headers=boss)
    r = await hub.get("/patreon/connect", headers=ann)
    assert r.status_code == 200 and "client_id=cid" in r.json()["url"]
    state = r.json()["url"].split("state=")[1]

    async def identity(_hub, code):
        assert code == "the-code"
        return _identity("pu1", "active_patron", ["t-gold"])

    hub.hub.patreon_identity = identity
    r = await hub.get("/patreon/callback", params={"code": "the-code", "state": state})
    assert r.status_code == 303 and r.headers["location"] == "https://play.test/?patreon=linked"
    me = (await hub.get("/me", headers=ann)).json()
    assert me["patron"] is True and {b["id"] for b in me["badges"]} == {"patron", "legate"}

    # a bad state never links
    r = await hub.get("/patreon/callback", params={"code": "the-code", "state": "junk"})
    assert r.status_code == 400

    # the webhook: an unsigned call is refused; a downgrade takes the tier badge away; a delete the rest
    member = {"data": {"type": "member", "attributes": {"patron_status": "active_patron", "currently_entitled_amount_cents": 300},
                       "relationships": {"user": {"data": {"id": "pu1"}}, "campaign": {"data": {"id": "camp"}},
                                         "currently_entitled_tiers": {"data": [{"id": "t-bronze"}]}}}}
    raw, sig = _signed(member)
    assert (await hub.post("/patreon/webhook", content=raw, headers={"X-Patreon-Signature": "bad"})).status_code == 401
    r = await hub.post("/patreon/webhook", content=raw, headers={"X-Patreon-Signature": sig, "X-Patreon-Event": "members:pledge:update"})
    assert r.status_code == 200, r.text
    assert {b["id"] for b in (await hub.get("/me", headers=ann)).json()["badges"]} == {"patron"}
    r = await hub.post("/patreon/webhook", content=raw, headers={"X-Patreon-Signature": sig, "X-Patreon-Event": "members:pledge:delete"})
    me = (await hub.get("/me", headers=ann)).json()
    assert me["patron"] is False and me["badges"] == []

    # a Patreon account links to one player only
    bob = await account(hub, "bob")
    state = (await hub.get("/patreon/connect", headers=bob)).json()["url"].split("state=")[1]
    r = await hub.get("/patreon/callback", params={"code": "the-code", "state": state})
    assert r.headers["location"].endswith("?patreon=patreon_taken")


@pytest.mark.parametrize("campaign,expected", [("camp", "active_patron"), ("someone-else", None)])
def test_membership_counts_only_our_campaign(campaign: str, expected: str | None) -> None:
    from ovian_hub.patreon import membership

    assert membership(_identity("u", "active_patron", ["t"], campaign), "camp")["patron_status"] == expected


async def test_spawning_a_world_from_the_hub(hub, monkeypatch) -> None:
    import ovian_hub.api as api

    boss = await account(hub, "boss")
    ann = await account(hub, "ann")
    calls: list[tuple[str, str]] = []

    async def fake_spawner(_hub, method: str, path: str, body: dict | None = None):
        calls.append((method, path))
        if method == "POST" and path == "/worlds":
            assert body is not None
            return {"id": body["id"], "pack": body["pack"], "speed": body["speed"], "database": f"ovian_{body['id']}", "api_url": f"/w/{body['id']}",
                    "internal_url": f"http://server-{body['id']}:8000", "mqtt_url": "", "state": "running", "containers": [], "overrides": body["overrides"]}
        if method == "GET":
            return []
        return {"id": path.split("/")[2], "state": "stopped", "containers": []}

    monkeypatch.setattr(api, "_spawner", fake_spawner)
    sc = (await hub.get("/admin/spawner/schema", headers=boss)).json()
    assert set(sc["modes"]) == {"hybrid", "pve", "pvp"} and len(sc["groups"]) >= 40 and sc["enabled"] is False
    assert (await hub.get("/admin/spawner/schema", headers=ann)).status_code == 403

    body = {"id": "w7", "name": "Seven", "mode": "pve", "speed": 5, "overrides": {"extensions": {"camps": {"count": 30}}}, "status": "open"}
    r = await hub.post("/admin/spawner/worlds", json=body, headers=boss)
    assert r.status_code == 201, r.text
    d = r.json()
    ext = d["overrides"]["extensions"]
    assert ext["pvp"] == {"enabled": False} and ext["camps"]["count"] == 30 and ext["treaties"] is None, "the preset, then the admin's overrides"
    assert d["world"]["api_url"] == "/w/w7" and d["world"]["status"] == "open" and d["world"]["speed"] == 5
    assert any(w["id"] == "w7" for w in (await hub.get("/worlds")).json()), "listed on the hub at once"
    assert (await hub.post("/admin/spawner/worlds", json=body, headers=boss)).status_code == 409
    assert (await hub.post("/admin/spawner/worlds", json=body | {"id": "w8", "mode": "nope"}, headers=boss)).status_code == 422

    assert (await hub.post("/admin/spawner/worlds/w7/stop", headers=boss)).status_code == 200
    assert next(w for w in (await hub.get("/admin/worlds", headers=boss)).json() if w["id"] == "w7")["status"] == "closed", "a stopped world is closed"
    assert (await hub.post("/admin/spawner/worlds/w7/start", headers=ann)).status_code == 403
    assert ("POST", "/worlds/w7/stop") in calls
