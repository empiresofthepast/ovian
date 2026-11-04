"""Players can change their username."""

from __future__ import annotations

from ovian_server.game import Game


async def test_change_username(game: Game, client, register):
    alice = await register("alice")
    await register("bob")
    r = await alice.post("/me/username", {"username": "Bob", "password": "password123"})
    assert r.json()["error"] == "username_taken"
    r = await alice.post("/me/username", {"username": "Alicia", "password": "wrong-pass"})
    assert r.status_code == 401
    r = await alice.post("/me/username", {"username": "no spaces", "password": "password123"})
    assert r.json()["error"] == "invalid_username"

    r = await alice.post("/me/username", {"username": "Alicia", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["player"]["username"] == "Alicia" and r.json()["token"]
    me = (await alice.get("/me")).json()
    assert me["username"] == "Alicia" and me["former_names"] == ["alice"] and me["rename_ready_at"] > game.clock.now()
    assert (await alice.village())["name"] == "Alicia's village"
    login = await client.post("/auth/login", json={"username": "alicia", "password": "password123"})
    assert login.status_code == 200
    assert (await client.post("/auth/login", json={"username": "alice", "password": "password123"})).status_code == 401

    r = await alice.post("/me/username", {"username": "Alice2", "password": "password123"})
    assert r.json()["error"] == "rename_too_soon"
    game.clock.value = me["rename_ready_at"]
    r = await alice.post("/me/username", {"username": "Alice2", "password": "password123"})
    assert r.status_code == 200, r.text
