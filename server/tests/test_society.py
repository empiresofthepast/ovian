"""Alliances, market, scouting, heroes, camps, quests, gods, great buildings, vacation, achievements and the wonder."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.modules import pve

from .conftest import give_buildings, patch_state


async def neighbours(game: Game, register, a="alice", b="bob"):
    alice = await register(a, "clans")
    bob = await register(b, "legion")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    target = await bob.village()
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, target["x"] + 2, target["y"])
    return alice, bob, target


async def arrive(game: Game, view: dict) -> None:
    game.clock.value = max(m["arrives_at"] for m in view["movements"]["outgoing"])
    await game.run_due()


async def last_report(player) -> dict:
    rid = (await player.get("/reports")).json()[0]["id"]
    return (await player.get(f"/reports/{rid}")).json()


async def test_alliances_pacts_and_chat(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    carol = await register("carol", "riders")
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 50}))

    a = (await alice.post("/alliances", {"name": "Northern League", "tag": "NL"})).json()
    assert a["members"][0]["role"] == "leader"
    assert (await alice.post("/alliance/invites", {"username": "bob"})).status_code == 201
    invites = (await bob.get("/alliance")).json()["invites"]
    assert invites[0]["tag"] == "NL"
    await bob.post(f"/alliances/{a['id']}/join")
    order = {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 10}}
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).json()["error"] == "same_alliance"

    # chat reaches members as private events
    await bob.post("/alliance/messages", {"text": "hail"})
    assert any(e["type"] == "alliance.message" for e in game.realtime.to(game.topics.player(alice.id)))
    assert [m["text"] for m in (await alice.get("/alliance/messages")).json()] == ["hail"]

    # a pact needs both sides; then no attacks
    await bob.post("/alliance/leave")
    await bob.post("/alliances", {"name": "Southern Realm", "tag": "SR"})
    await alice.post("/alliance/diplomacy", {"tag": "SR", "kind": "nap"})
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).status_code == 200, "only proposed so far"
    await bob.post("/alliance/diplomacy", {"tag": "NL", "kind": "nap"})
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).json()["error"] == "pact"
    await bob.post("/alliance/diplomacy", {"tag": "NL", "kind": "war"})
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).status_code == 200
    assert {r["tag"] for r in (await carol.get("/alliances")).json()} == {"NL", "SR"}
    area = (await alice.get("/map", params={"x": target["x"], "y": target["y"], "w": 1, "h": 1})).json()
    assert area["villages"][0]["alliance_tag"] == "SR"


async def test_market_ships_and_trades(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    for p in (alice, bob):
        await patch_state(game, p.village_id, lambda s: (give_buildings(s, town_hall=5, market=3, warehouse=10, granary=10),
                                                         s.__setitem__("resources", {r: 5000 for r in s["resources"]})))
    url = f"/villages/{alice.village_id}/market"
    v = (await alice.post(f"{url}/send", {"x": target["x"], "y": target["y"], "resources": {"wood": 1500}})).json()
    assert v["market"]["busy"] == 2 and v["state"]["resources"]["wood"] < 3600
    assert (await alice.post(f"{url}/send", {"x": target["x"], "y": target["y"], "resources": {"clay": 1500}})).json()["error"] == "no_merchants"
    game.clock.value = v["market"]["shipments"][0]["arrives_at"]
    await game.run_due()
    assert (await bob.village())["state"]["resources"]["wood"] > 6000

    # an offer: alice gives iron for bob's grain
    game.clock.value += 3_600_000
    await game.run_due()
    await alice.post(f"{url}/offers", {"give": {"iron": 900}, "want": {"grain": 1000}})
    offer = next(o for o in (await bob.get("/market/offers", params={"village_id": bob.village_id})).json() if not o["mine"])
    v = (await bob.post(f"/market/offers/{offer['id']}/accept?village_id={bob.village_id}")).json()
    assert v["market"]["busy"] == 1
    game.clock.value = max(s["arrives_at"] for s in v["market"]["shipments"])
    await game.run_due()
    assert (await alice.village())["state"]["resources"]["grain"] > 4500


async def test_scouting_and_simulator(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 20}))
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"legionary": 30}))
    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "scout", "x": target["x"], "y": target["y"], "units": {"clubman": 5}})).json()
    await arrive(game, v)
    r = await last_report(alice)
    assert r["kind"] == "scout" and r["data"]["success"] and r["data"]["units"] == {"legionary": 30}
    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "scout", "x": target["x"], "y": target["y"], "units": {"clubman": 2}})).json()
    await arrive(game, v)
    assert not (await last_report(alice))["data"]["success"], "2 scouts cannot slip past 30 defenders"
    sim = (await alice.post("/simulate", {"attackers": {"clubman": 100}, "defenders": {"legionary": 5}})).json()
    assert sim["attacker_won"]


async def test_hero_leads_armies_and_grows(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    h = (await alice.get("/hero")).json()
    assert h["hero"] is None and h["candidates"]
    await alice.post("/hero", {"template": h["candidates"][0]["id"], "village_id": alice.village_id})
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 200}))
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"legionary": 40}))
    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "attack", "x": target["x"], "y": target["y"], "units": {"clubman": 150}, "hero": True})).json()
    assert (await alice.get("/hero")).json()["hero"]["status"] == "away"
    await arrive(game, v)
    report = await last_report(alice)
    assert report["data"]["heroes"]["attacker"]["xp"] > 0
    await arrive(game, await alice.village())
    hero = (await alice.get("/hero")).json()["hero"]
    assert hero["status"] == "home" and hero["level"] >= 1
    before = (await alice.village())["economy"]["production"]["wood"]
    await alice.post("/hero/points", {"production": 1})
    assert (await alice.village())["economy"]["production"]["wood"] > before


async def test_barbarian_camps_and_quests(game: Game, client, register):
    alice = await register("alice", "clans")
    async with game.tx() as tx:
        assert await pve.maintain(game, tx) >= 12
    camps = await game.pool.fetch("SELECT v.x, v.y, v.meta FROM villages v JOIN players p ON p.id = v.player_id WHERE p.npc")
    camp = min(camps, key=lambda c: c["meta"]["camp"]["level"])
    assert all(r["username"] != "Barbarians" for r in (await alice.get("/rankings")).json())
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"axeman": 400}))
    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "raid", "x": camp["x"], "y": camp["y"], "units": {"axeman": 400}})).json()
    await arrive(game, v)
    report = await last_report(alice)
    assert report["data"]["winner"] == "attacker" and report["data"]["camp"]
    assert "submission" not in report["data"], "camps are not submitted"

    q = (await alice.get("/quests")).json()
    assert q["total"] >= 10 and len(q["quests"]) == 3
    camp_q = next((x for x in (await alice.get("/quests")).json()["quests"] if x["id"] == "woodcutter"), None)
    assert camp_q and not camp_q["complete"]
    await patch_state(game, alice.village_id, lambda s: s["slots"][0].__setitem__("level", 2))
    before = (await alice.village())["state"]["resources"]["wood"]
    v = (await alice.post(f"/quests/woodcutter/claim?village_id={alice.village_id}")).json()
    assert v["state"]["resources"]["wood"] >= before + 199
    assert (await alice.post(f"/quests/woodcutter/claim?village_id={alice.village_id}")).json()["error"] == "quest_claimed"


async def test_gods_favor_and_powers(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: give_buildings(s, temple=10))
    v = await alice.village()
    assert v["gods"]["rate"] > 0
    game.clock.value += 3_600_000  # an hour at world speed 1 gives 20 favor at temple 10
    assert (await alice.post(f"/villages/{alice.village_id}/powers/blessing", {})).json()["error"] == "no_favor"
    game.clock.value += 10 * 3_600_000
    before = (await alice.village())["economy"]["production"]["wood"]
    v = (await alice.post(f"/villages/{alice.village_id}/powers/blessing", {})).json()
    assert v["economy"]["production"]["wood"] > before and v["gods"]["blessing"]
    game.clock.value = v["gods"]["blessing"]["until"]
    await game.run_due()
    assert abs((await alice.village())["economy"]["production"]["wood"] - before) < 1e-6

    game.clock.value += 20 * 3_600_000
    bob_wood = (await bob.village())["state"]["resources"]["wood"]
    await alice.post(f"/villages/{alice.village_id}/powers/wrath", {"x": target["x"], "y": target["y"]})
    assert (await bob.village())["state"]["resources"]["wood"] < bob_wood


async def test_great_buildings_take_contributions(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, bob.village_id, lambda s: give_buildings(s, town_hall=10, temple=5, great_theatre=1))
    await patch_state(game, alice.village_id, lambda s: (give_buildings(s, warehouse=20, granary=20), s.__setitem__("resources", {r: 50_000 for r in s["resources"]})))
    g = (await bob.village())["great"][0]
    assert g["building"] == "great_theatre" and g["next_level"] == 2
    near = (await alice.get("/great-buildings", params={"x": target["x"], "y": target["y"]})).json()
    assert near[0]["village"]["id"] == bob.village_id
    gift = {r: 20_000 for r in ("wood", "clay", "iron", "grain")}
    v = (await alice.post(f"/villages/{bob.village_id}/great/great_theatre/contribute", {"from_village_id": alice.village_id, "resources": gift})).json()
    assert v["id"] == alice.village_id, "the donor sees their own city"
    g = (await bob.village())["great"][0]
    assert g["level"] == 2 and g["points"] == 0
    reports = (await alice.get("/reports")).json()
    assert any(r["kind"] == "great" for r in reports)


async def test_vacation_achievements_and_wonder(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 50}))
    await bob.post("/me/vacation", {"hours": 24})
    order = {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 50}}
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).json()["error"] == "target_on_vacation"
    assert (await bob.post(f"/villages/{bob.village_id}/build", {"slot": 0})).json()["error"] == "on_vacation"
    assert (await bob.post("/me/vacation/end")).json()["error"] == "vacation_too_short"
    game.clock.value += 13 * 3_600_000
    await bob.post("/me/vacation/end")
    v = (await alice.post(f"/villages/{alice.village_id}/send", order)).json()
    await arrive(game, v)
    ach = {a["id"]: a for a in (await alice.get("/achievements")).json()}
    assert ach["first_blood"]["unlocked_at"]

    def wonder(s):
        give_buildings(s, town_hall=20, temple=10, university=10, warehouse=20, granary=20, wonder=24)
        s["resources"] = {r: 900_000 for r in s["resources"]}

    await patch_state(game, alice.village_id, wonder)
    slot = next(i for i, s in enumerate((await alice.village())["state"]["slots"]) if s["building"] == "wonder")
    v = (await alice.post(f"/villages/{alice.village_id}/build", {"slot": slot})).json()
    game.clock.value = v["build_queue"][0]["due_at"]
    await game.run_due()
    win = (await bob.get("/world/victory")).json()
    assert win["winner"]["player"]["name"] == "alice" and win["race"][0]["level"] == 25
