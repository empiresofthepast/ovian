"""Superusers see who has connected, who is online and which cities each player holds."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.presence import ONLINE_MS


async def test_admin_lists_players_and_presence(game: Game, client, register):
    game.settings.admin_users = "Boss"
    boss = await register("boss", "legion")
    alice = await register("alice", "clans")
    me = (await boss.get("/me")).json()
    assert me["is_admin"] is True
    assert (await alice.get("/me")).json()["is_admin"] is False
    assert (await alice.get("/admin/players")).status_code == 403

    # alice logs in again and calls the API; then time passes without her
    await client.post("/auth/login", json={"username": "alice", "password": "password123"})
    data = (await boss.get("/admin/players")).json()
    row = next(p for p in data["players"] if p["username"] == "alice")
    assert row["logins"] == 2 and row["connected"] and row["online"]
    assert row["own_cities"] == 1 and row["cities"][0]["id"] == alice.village_id
    assert data["totals"]["players"] == 2 and data["totals"]["with_own_city"] == 2

    game.clock.value = game.clock.now() + ONLINE_MS + 60_000
    await boss.post("/me/heartbeat")
    data = (await boss.get("/admin/players")).json()
    online = {p["username"]: p["online"] for p in data["players"]}
    assert online == {"boss": True, "alice": False}
    assert data["players"][0]["username"] == "boss", "most recently seen first"
    # superusers can look into any city, others cannot
    v = (await boss.get(f"/admin/villages/{alice.village_id}")).json()
    assert v["id"] == alice.village_id and v["owner"]["name"] == "alice" and "economy" in v
    assert (await alice.get(f"/admin/villages/{boss.village_id}")).status_code == 403
    game.settings.admin_users = ""
