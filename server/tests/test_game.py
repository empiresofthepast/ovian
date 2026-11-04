from __future__ import annotations

import json

from ovian_server.game import Game
from ovian_server.hooks import hookimpl

from .conftest import give_buildings, patch_state, rich


async def test_register_login_me(client, register):
    alice = await register("alice", "legion")
    dup = await client.post("/auth/register", json={"username": "ALICE", "password": "password123", "tribe": "legion"})
    assert dup.status_code == 409 and dup.json()["error"] == "username_taken"
    bad = await client.post("/auth/register", json={"username": "bob", "password": "password123", "tribe": "elves"})
    assert bad.json()["error"] == "unknown_tribe"

    r = await client.post("/auth/login", json={"username": "alice", "password": "password123"})
    assert r.status_code == 200
    wrong = await client.post("/auth/login", json={"username": "alice", "password": "nope-nope"})
    assert wrong.status_code == 401

    me = (await alice.get("/me")).json()
    assert me["tribe"] == "legion" and len(me["villages"]) == 1
    assert me["protected_until"] > 0, "beginner protection plugin is active"
    assert (await client.get("/me")).status_code == 401


async def test_public_world(client, register):
    alice = await register("alice")
    v = await alice.village()
    world = (await client.get("/world")).json()
    assert world["pack"]["id"] == "classic"
    area = (await client.get("/map", params={"x": v["x"] - 2, "y": v["y"] - 2, "w": 5, "h": 5})).json()
    assert len(area["tiles"]) == 25
    assert [x["name"] for x in area["villages"]] == ["alice's village"]
    ranking = (await client.get("/rankings")).json()
    assert ranking[0]["username"] == "alice" and ranking[0]["population"] == 3
    assert (await client.get("/content")).json()["extensions"]["beginner_protection_hours"] == 72


async def test_construction(game: Game, client, register):
    alice = await register("alice")
    before = await alice.village()
    assert before["state"]["slots"][0] == {"building": "woodcutter", "level": 0}

    r = await alice.post(f"/villages/{alice.village_id}/build", {"slot": 0})
    assert r.status_code == 200, r.text
    v = r.json()
    assert len(v["build_queue"]) == 1
    assert v["state"]["resources"]["clay"] < before["state"]["resources"]["clay"] - 99

    # second order on the same slot queues level 2 after level 1
    v = (await alice.post(f"/villages/{alice.village_id}/build", {"slot": 0})).json()
    assert [q["level"] for q in v["build_queue"]] == [1, 2]
    full = await alice.post(f"/villages/{alice.village_id}/build", {"slot": 1})
    assert full.json()["error"] == "queue_full"

    # cancelling level 1 is refused while level 2 is queued; cancelling level 2 refunds it
    l1, l2 = v["build_queue"]
    assert (await alice.delete(f"/villages/{alice.village_id}/jobs/{l1['id']}")).json()["error"] == "cancel_later_first"
    v = (await alice.delete(f"/villages/{alice.village_id}/jobs/{l2['id']}")).json()
    assert len(v["build_queue"]) == 1

    game.clock.advance(3600)
    assert await game.run_due() == 1
    v = await alice.village()
    assert v["state"]["slots"][0] == {"building": "woodcutter", "level": 1}
    assert v["economy"]["production"]["wood"] == 14
    events = game.realtime.to(game.topics.player(alice.id))
    assert "build.completed" in [e["type"] for e in events]
    assert events[-1]["type"] == "village.updated"
    assert events[-1]["data"]["build_queue"] == [], "the pushed view no longer lists the finished job"


async def test_rule_errors(client, register):
    alice = await register("alice")
    vid = alice.village_id
    assert (await alice.post(f"/villages/{vid}/build", {"slot": 20, "building": "barracks"})).json()["error"] == "requirements"
    assert (await alice.post(f"/villages/{vid}/build", {"slot": 99})).json()["error"] == "invalid_slot"
    assert (await alice.post(f"/villages/{vid}/train", {"unit": "clubman", "count": 1})).json()["error"] == "requirements"
    bob = await register("bob")
    assert (await bob.get(f"/villages/{vid}")).status_code == 403


async def test_training_catches_up(game: Game, client, register):
    alice = await register("alice", "clans")
    await patch_state(game, alice.village_id, lambda s: (rich(s), give_buildings(s, barracks=1)))
    v = (await alice.post(f"/villages/{alice.village_id}/train", {"unit": "clubman", "count": 5})).json()
    assert v["training"][0]["remaining"] == 5
    game.clock.advance(600 * 3 + 1)  # three units are due
    await game.run_due()
    v = await alice.village()
    assert v["state"]["units"] == {"clubman": 3}
    assert v["training"][0]["remaining"] == 2
    game.clock.advance(1200)
    await game.run_due()
    assert (await alice.village())["state"]["units"] == {"clubman": 5}


async def test_raid_and_return(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 50}))
    target = await bob.village()
    order = {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 50}}

    blocked = await alice.post(f"/villages/{alice.village_id}/send", order)
    assert blocked.json()["error"] == "target_protected"
    tile = (await alice.get("/map", params={"x": target["x"], "y": target["y"], "w": 1, "h": 1})).json()["villages"][0]
    assert tile["protected"] and tile["protected_until"] > game.clock.now(), "clients can hide Attack and Raid"
    await game.pool.execute("UPDATE players SET protected_until = 0")

    too_many = await alice.post(f"/villages/{alice.village_id}/send", order | {"units": {"clubman": 51}})
    assert too_many.json()["error"] == "not_enough_units"
    v = (await alice.post(f"/villages/{alice.village_id}/send", order)).json()
    assert v["state"]["units"] == {}
    out = v["movements"]["outgoing"][0]
    incoming = (await bob.village())["movements"]["incoming"][0]
    assert "units" not in incoming, "attackers are hidden from the defender"
    assert any(e["type"] == "movement.incoming" for e in game.realtime.to(game.topics.player(bob.id)))

    game.clock.value = out["arrives_at"]
    await game.run_due()
    reports = (await alice.get("/reports")).json()
    assert reports[0]["kind"] == "battle" and "(won)" in reports[0]["title"]
    full = (await alice.get(f"/reports/{reports[0]['id']}")).json()
    loot = full["data"]["loot"]
    assert sum(loot.values()) > 0
    assert (await bob.get("/reports")).json()[0]["title"].endswith("(lost)")

    back = (await alice.village())["movements"]["outgoing"][0]
    assert back["kind"] == "return"
    game.clock.value = back["arrives_at"]
    await game.run_due()
    v = await alice.village()
    assert v["state"]["units"]["clubman"] == 50
    assert v["state"]["resources"]["wood"] > 750


async def test_reinforce_defend_and_recall(game: Game, client, register):
    alice = await register("alice", "legion")
    bob = await register("bob", "legion")
    eve = await register("eve", "clans")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"guardian": 40}))
    await patch_state(game, eve.village_id, lambda s: s.__setitem__("units", {"clubman": 30}))
    bv = await bob.village()

    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "reinforce", "x": bv["x"], "y": bv["y"], "units": {"guardian": 40}})).json()
    game.clock.value = v["movements"]["outgoing"][0]["arrives_at"]
    await game.run_due()
    here = (await bob.village())["reinforcements"]["here"]
    assert here[0]["units"] == {"guardian": 40}
    assert (await bob.village())["economy"]["upkeep"] > bv["economy"]["upkeep"], "host feeds the reinforcement"

    e = (await eve.post(f"/villages/{eve.village_id}/send", {"kind": "attack", "x": bv["x"], "y": bv["y"], "units": {"clubman": 30}})).json()
    game.clock.value = e["movements"]["outgoing"][0]["arrives_at"]
    await game.run_due()
    assert "(lost)" in (await eve.get("/reports")).json()[0]["title"]
    alice_reports = (await alice.get("/reports")).json()
    assert alice_reports[0]["title"] == "Your troops fought in bob's village"
    stationed = (await bob.village())["reinforcements"]["here"][0]
    assert 0 < stationed["units"]["guardian"] < 40

    v = (await alice.post(f"/villages/{alice.village_id}/reinforcements/{stationed['id']}/recall")).json()
    game.clock.value = v["movements"]["outgoing"][0]["arrives_at"]
    await game.run_due()
    assert (await alice.village())["state"]["units"]["guardian"] == stationed["units"]["guardian"]


async def test_chat_over_mqtt_and_rest(game: Game, client, register):
    alice = await register("alice")
    await game.realtime.deliver(game.topics.chat_in("global", alice.id), json.dumps({"text": "hello"}).encode())
    msgs = game.realtime.to(game.topics.chat("global"))
    assert msgs[0]["data"]["from"] == {"id": alice.id, "name": "alice"}
    assert (await alice.post("/chat/global", {"text": "too fast"})).status_code == 429
    assert (await alice.post("/chat/nowhere", {"text": "x"})).status_code == 404
    history = (await client.get("/chat/global")).json()
    assert [m["text"] for m in history] == ["hello"]


async def test_mqtt_auth_endpoints(game: Game, client, register):
    alice = await register("alice")
    base = "http://test/internal/mqtt"
    root = game.topics.root

    async def call(path: str, key: str = "test-key", **body):
        return (await client.post(f"{base}/{path}", params={"key": key}, json=body)).status_code

    assert await call("user", username=str(alice.id), password=alice.token) == 200
    assert await call("user", username="999", password=alice.token) == 403
    assert await call("user", key="wrong", username=str(alice.id), password=alice.token) == 403
    assert await call("user", username="ovian-server", password="dev-service-password") == 200
    assert await call("superuser", username="ovian-server") == 200
    assert await call("superuser", username=str(alice.id)) == 403

    def acl(topic: str, acc: int) -> dict:
        return {"username": str(alice.id), "topic": topic, "acc": acc}

    assert await call("acl", **acl(f"{root}/player/{alice.id}/events", 4)) == 200
    assert await call("acl", **acl(f"{root}/player/{alice.id}/#", 4)) == 200
    assert await call("acl", **acl(f"{root}/player/999/events", 4)) == 403
    assert await call("acl", **acl(f"{root}/player/+/events", 4)) == 403
    assert await call("acl", **acl(f"{root}/chat/+", 4)) == 200
    assert await call("acl", **acl(f"{root}/chat/#", 4)) == 403
    assert await call("acl", **acl(f"{root}/map", 1)) == 200
    assert await call("acl", **acl(f"{root}/chat/global/in/{alice.id}", 2)) == 200
    assert await call("acl", **acl(f"{root}/chat/global/in/999", 2)) == 403
    assert await call("acl", **acl(f"{root}/chat/global", 2)) == 403
    assert await call("acl", **acl(f"{root}/map", 2)) == 403


async def test_plugin_hooks_change_battles(game: Game, client, register):
    class Pacifism:
        @hookimpl
        def ovian_battle_prepare(self, battle, **_):
            battle["attack_multiplier"] = 0.0

    plugin = Pacifism()
    game.pm.register(plugin)
    try:
        alice = await register("alice", "clans")
        bob = await register("bob")
        await game.pool.execute("UPDATE players SET protected_until = 0")
        await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 10}))
        bv = await bob.village()
        v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "attack", "x": bv["x"], "y": bv["y"], "units": {"clubman": 10}})).json()
        game.clock.value = v["movements"]["outgoing"][0]["arrives_at"]
        await game.run_due()
        assert "(lost)" in (await alice.get("/reports")).json()[0]["title"]
    finally:
        game.pm.unregister(plugin)


async def test_delete_account(game: Game, client, register):
    from ovian_server.modules.submission import submit
    from ovian_server.repo import get_village

    from .test_society import neighbours

    alice, bob, target = await neighbours(game, register)
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"axeman": 10}))
    a = (await alice.post("/alliances", {"name": "Short Lived", "tag": "SL"})).json()
    # bob is alice's vassal, has troops in her city and an army on its way there
    async with game.tx() as tx:
        await submit(game, tx, await get_village(tx.conn, bob.village_id, lock=True), await get_village(tx.conn, alice.village_id, lock=True))
    alice_v = await alice.village()
    r = await bob.post(f"/villages/{bob.village_id}/send", {"kind": "reinforce", "x": alice_v["x"], "y": alice_v["y"], "units": {"axeman": 4}})
    assert r.status_code == 200, r.text
    game.clock.value = r.json()["movements"]["outgoing"][0]["arrives_at"]
    await game.run_due()
    r = await bob.post(f"/villages/{bob.village_id}/send", {"kind": "reinforce", "x": alice_v["x"], "y": alice_v["y"], "units": {"axeman": 6}})
    assert r.status_code == 200, r.text

    assert (await alice.post("/me/delete", {"password": "wrong", "confirm": "alice"})).status_code == 401
    assert (await alice.post("/me/delete", {"password": "password123", "confirm": "nope"})).json()["error"] == "confirm_username"
    r = await alice.post("/me/delete", {"password": "password123", "confirm": "Alice"})
    assert r.status_code == 200, r.text

    assert not await game.pool.fetchval("SELECT 1 FROM players WHERE username = 'alice'")
    assert not await game.pool.fetchval("SELECT 1 FROM villages WHERE id = $1", alice.village_id)
    assert not await game.pool.fetchval("SELECT 1 FROM alliances WHERE id = $1", a["id"])
    v = await bob.village()
    assert not v["submission"] and not v["state"].get("tribute")  # free again
    assert v["state"]["units"]["axeman"] == 10  # every soldier home
    assert v["movements"]["outgoing"] == []
    assert (await alice.get("/me")).status_code in (401, 404)
