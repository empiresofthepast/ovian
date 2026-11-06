"""Trade profit and bandits, abandoned cities, the barbarian horde, treaties."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.modules import abandon, horde, pve

from .conftest import give_buildings, patch_state
from .test_realm import extensions
from .test_society import arrive, last_report, neighbours

TRADE = {"profit_per_tile": 0.05, "profit_max": 0.5, "profit_cap_per_level": 10_000, "bandits_from": 100}


async def _traders(game: Game, register):
    alice, bob, target = await neighbours(game, register)
    for p in (alice, bob):
        await patch_state(game, p.village_id, lambda s: (give_buildings(s, town_hall=5, market=3, warehouse=10, granary=10),
                                                         s.__setitem__("resources", {r: 5000 for r in s["resources"]})))
    return alice, bob, target


async def _deliver(game: Game, view: dict) -> None:
    game.clock.value = max(s["arrives_at"] for s in view["market"]["shipments"])
    await game.run_due()
    game.clock.value += 24 * 3_600_000  # the merchants come home
    await game.run_due()


async def test_merchants_earn_abroad_and_leave_no_reports(game: Game, client, register):
    alice, bob, target = await _traders(game, register)
    with extensions(game, trade=TRADE):
        v = (await alice.post(f"/villages/{alice.village_id}/market/send", {"x": target["x"], "y": target["y"], "resources": {"wood": 1000}})).json()
        assert v["market"]["trade"]["profit_today"] == 0
        await _deliver(game, v)
        a = await alice.village()
    assert a["state"]["resources"]["wood"] >= 4000 + 100 - 1, "2 tiles at 5% a tile: a tenth of the cargo comes back as profit"
    assert not [r for r in (await alice.get("/reports")).json() if r["kind"] == "trade"]
    assert not [r for r in (await bob.get("/reports")).json() if r["kind"] == "trade"]


async def test_bandits_rob_caravans_off_the_roads(game: Game, client, register):
    alice, bob, target = await _traders(game, register)
    before = (await bob.village())["state"]["resources"]["wood"]
    with extensions(game, trade=TRADE | {"bandits_from": 0, "bandits_per_tile": 1, "bandits_max": 1, "bandits_take": 0.5}):
        v = (await alice.post(f"/villages/{alice.village_id}/market/send", {"x": target["x"], "y": target["y"], "resources": {"wood": 1000}})).json()
        await _deliver(game, v)
    got = (await bob.village())["state"]["resources"]["wood"] - before
    assert 490 <= got < 1000, "bandits took half"
    r = await last_report(alice)
    assert r["kind"] == "trade" and r["data"]["robbed"] == {"wood": 500}


async def test_abandoned_cities_fall_to_the_barbarians(game: Game, client, register):
    alice = await register("alice", "clans")
    await register("bob", "legion")
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 7}))
    await game.pool.execute("UPDATE players SET last_seen_at = $2, last_login_at = $2 WHERE username = $1", "alice", game.clock.now())
    with extensions(game, abandon={"days": 7}):
        async with game.tx() as tx:
            assert await abandon.sweep(game, tx) == 0
        game.clock.value += 8 * 86_400_000
        await game.pool.execute("UPDATE players SET last_seen_at = $1 WHERE username = 'bob'", game.clock.now())
        async with game.tx() as tx:
            assert await abandon.sweep(game, tx) == 1
    ruin = await game.pool.fetchrow("SELECT v.name, v.meta, v.state, p.npc FROM villages v JOIN players p ON p.id = v.player_id WHERE v.id = $1",
                                    alice.village_id)
    assert ruin["npc"] and ruin["name"].startswith("Ruins of") and ruin["meta"]["camp"]["level"] >= 1
    assert ruin["state"]["units"] == {"clubman": 7}, "the troops left behind defend the ruins"
    me = (await alice.get("/me")).json()  # back after all: a fresh start
    assert len(me["villages"]) == 1 and me["villages"][0]["id"] != alice.village_id


async def test_the_horde_marches_on_the_strongest(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await game.pool.execute("UPDATE players SET last_seen_at = $1", game.clock.now())
    await game.pool.execute("UPDATE villages SET population = 500 WHERE id = $1", bob.village_id)
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {}))
    async with game.tx() as tx:
        await pve.maintain(game, tx)
    with extensions(game, horde={"min_troops": 30, "warning_hours": 0}):
        async with game.tx() as tx:
            m = await horde.gather(game, tx)
        assert m["to_id"] == bob.village_id
        game.clock.value = m["arrives_at"]
        await game.run_due()
    r = await last_report(bob)
    assert r["kind"] == "battle" and r["data"]["horde"] and r["data"]["winner"] == "attacker"
    assert not await game.pool.fetchval("SELECT 1 FROM movements WHERE home_id = $1", m["home_id"]), "the horde breaks up"
    assert "horde" in [e["kind"] for e in (await alice.get("/chronicle")).json()["entries"]]


async def test_pacts_tribute_and_treachery(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: (give_buildings(s, warehouse=10, granary=10), s.__setitem__("units", {"clubman": 50}),
                                                         s.__setitem__("resources", {r: 5000 for r in s["resources"]})))
    await patch_state(game, bob.village_id, lambda s: give_buildings(s, warehouse=10, granary=10))
    t = (await alice.post("/treaties", {"to": "bob", "tribute": {"payer": "me", "resources": {"wood": 100}, "every_hours": 2}})).json()
    assert t["status"] == "proposed" and t["tribute"]["i_pay"]
    assert (await alice.post(f"/treaties/{t['id']}/accept")).json()["error"] == "not_yours_to_accept"
    assert (await bob.post(f"/treaties/{t['id']}/accept")).json()["status"] == "active"
    before = (await bob.village())["state"]["resources"]["wood"]
    game.clock.value += 2 * 3_600_000
    await game.run_due()
    assert (await bob.village())["state"]["resources"]["wood"] >= before + 100
    assert (await bob.get("/treaties")).json()["treaties"][0]["last_paid_at"]

    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 10}})).json()
    assert v["id"] == alice.village_id, v
    assert (await alice.get("/treaties")).json()["treaties"] == []
    assert (await alice.get("/treaties")).json()["treacherous_until"] > game.clock.now()
    tiles = (await alice.get("/map", params={"x": target["x"] - 1, "y": target["y"] - 1, "w": 5, "h": 3})).json()["villages"]
    assert next(x for x in tiles if x["id"] == alice.village_id)["treacherous"]
    assert any("broke your pact" in r["title"] for r in (await bob.get("/reports")).json())


async def test_mark_all_reports_read(game: Game, register):
    alice = await register("alice")
    bob = await register("bob")
    for t in ("one", "two", "three"):
        await game.pool.execute("INSERT INTO reports (player_id, kind, title, data, created_at) VALUES ($1, 'test', $2, '{}', 0)", alice.id, t)
    await game.pool.execute("INSERT INTO reports (player_id, kind, title, data, created_at) VALUES ($1, 'test', 'theirs', '{}', 0)", bob.id)
    assert (await alice.get("/me")).json()["unread_reports"] == 3
    assert (await alice.post("/reports/read")).json() == {"marked": 3}
    assert (await alice.get("/me")).json()["unread_reports"] == 0
    assert all(r["read"] for r in (await alice.get("/reports")).json())
    assert (await bob.get("/me")).json()["unread_reports"] == 1, "only your own reports"


async def test_cities_keep_their_distance(game: Game, register):
    from ovian_server.modules.auth import found_village_at

    players = [await register(f"player{i}") for i in range(12)]
    rows = await game.pool.fetch("SELECT x, y FROM villages")
    assert len(rows) == 12
    assert all(a == b or ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) >= 9 for a in rows for b in rows), "three tiles apart"
    home = await players[0].village()
    async with game.tx() as tx:
        assert await found_village_at(game, tx, players[0].id, "Too close", home["x"] + 2, home["y"]) is None


async def test_mountains_and_forests_around_a_city(game: Game, register):
    from ovian_server.modules import terrain

    alice = await register("alice")
    tiles = {(t["x"], t["y"]): t["terrain"] for t in game.engine.tiles(0, 0, 60, 60)}
    near = lambda x, y, kind: sum(1 for dx in range(-2, 3) for dy in range(-2, 3) if (dx, dy) != (0, 0) and tiles.get((x + dx, y + dy)) == kind)
    spot = next((x, y) for (x, y), t in tiles.items() if 2 < x < 57 and 2 < y < 57 and t == "plain"
                and near(x, y, "forest") >= 2 and not near(x, y, "mountain") and not near(x, y, "hills"))
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, *spot)
    from ovian_server.repo import refresh_all

    await refresh_all(game)
    v = await alice.village()
    assert v["state"]["boost_by"].get("wood") == round(0.05 * near(*spot, "forest"), 4), v["state"].get("boost_by")
    assert v["terrain"]["around"]["forest"] == near(*spot, "forest")
    assert v["terrain"]["bonus"] == {"wood": round(0.05 * near(*spot, "forest"), 4)}
    assert terrain.bonus(game, *spot) == v["terrain"]["bonus"]
