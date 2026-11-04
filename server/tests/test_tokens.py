"""Personal access tokens and the options endpoint (used by the MCP server)."""

from __future__ import annotations

from ovian_server.game import Game


async def test_personal_access_tokens(game: Game, client, register):
    alice = await register("alice")
    r = await alice.post("/me/tokens", {"name": "Claude"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert token.startswith("ovp_") and r.json()["prefix"] == token[:10]
    pat = {"Authorization": f"Bearer {token}"}

    me = await client.get("/me", headers=pat)
    assert me.status_code == 200 and me.json()["username"] == "alice"
    v = await client.post(f"/villages/{alice.village_id}/build", json={"slot": 0}, headers=pat)
    assert v.status_code == 200, v.text
    # account settings need the password login
    assert (await client.post("/me/tokens", json={"name": "x"}, headers=pat)).json()["error"] == "needs_login"
    assert (await client.post("/me/username", json={"username": "Alicia", "password": "password123"}, headers=pat)).json()["error"] == "needs_login"

    listed = (await alice.get("/me/tokens")).json()
    assert [t["name"] for t in listed] == ["Claude"] and listed[0]["last_used_at"] and "token" not in listed[0]
    assert (await alice.delete(f"/me/tokens/{listed[0]['id']}")).status_code == 204
    assert (await client.get("/me", headers=pat)).status_code == 401
    assert (await client.get("/me", headers={"Authorization": "Bearer ovp_nonsense"})).status_code == 401


async def test_city_options(game: Game, client, register):
    alice = await register("alice")
    o = (await alice.get(f"/villages/{alice.village_id}/options")).json()
    assert o["free_sites"] and o["upgrades"]
    up = o["upgrades"][0]
    assert up["slot"] == 0 and up["level"] == 0 and up["cost"] and up["seconds"] > 0 and "affordable" in up
    assert any("blocked" not in b for b in o["new_buildings"])
    assert any(b.get("blocked") for b in o["new_buildings"])
    assert o["units"] and all("unit" in u for u in o["units"])
    bob = await register("bob")
    assert (await bob.get(f"/villages/{alice.village_id}/options")).status_code in (403, 404)
