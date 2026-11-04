"""Five wins in a row make a city a vassal: it pays tribute and its culture serves the overlord."""

from __future__ import annotations

from ovian_server.game import Game

from .conftest import give_buildings, patch_state
from .test_culture import set_culture


async def raid(game: Game, attacker, target: dict, units: dict, kind: str = "raid") -> dict:
    v = (await attacker.post(f"/villages/{attacker.village_id}/send", {"kind": kind, "x": target["x"], "y": target["y"], "units": units})).json()
    game.clock.value = max(m["arrives_at"] for m in v["movements"]["outgoing"])
    await game.run_due()
    report_id = (await attacker.get("/reports")).json()[0]["id"]
    return (await attacker.get(f"/reports/{report_id}")).json()["data"]


async def test_five_wins_submit_a_city(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    target = await bob.village()
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, target["x"] + 2, target["y"])
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 500}))
    await patch_state(game, bob.village_id, lambda s: give_buildings(s, temple=5))
    await set_culture(game, bob.village_id)
    free = (await bob.village())["economy"]
    lord_before = (await alice.village())["economy"]

    for n in range(1, 5):
        report = await raid(game, alice, target, {"clubman": 20})
        assert report["winner"] == "attacker"
        assert report["submission"] == {"needed": 5, "wins": n}
    v = await bob.village()
    assert v["submission"] is None and v["dominance"]["threats"][0]["wins"] == 4
    assert (await alice.village())["dominance"]["conquests"][0]["wins"] == 4

    report = await raid(game, alice, target, {"clubman": 20})
    assert report["submission"]["submitted"] and report["submission"]["tribute"] == 0.1
    assert any(e["type"] == "village.submitted" for e in game.realtime.to(game.topics.player(bob.id)))

    # the vassal pays 10% of its gross production, the overlord receives it; it produces 5% more under protection
    v = await bob.village()
    assert v["submission"]["village"]["id"] == alice.village_id and v["submission"]["tribe"] == "clans"
    eco = v["economy"]
    for r, gross in eco["gross"].items():
        assert abs(eco["tribute_out"][r] - gross * 0.1) < 1e-6
        upkeep = free["gross"][r] - free["production"][r]
        assert abs(gross - free["gross"][r] * 1.05) < 1e-6
        assert abs(eco["production"][r] - (gross * 0.9 - upkeep)) < 1e-6
    lord = await alice.village()
    assert lord["vassals"][0]["village"]["id"] == bob.village_id
    assert lord["economy"]["tribute_in"] == eco["tribute_out"]
    assert lord["economy"]["production"]["wood"] > lord_before["production"]["wood"]

    # tribute follows the vassal's growth
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("resources", {r: 5_000 for r in s["resources"]}))
    v = (await bob.post(f"/villages/{bob.village_id}/build", {"slot": 0})).json()
    game.clock.value = v["build_queue"][0]["due_at"]
    await game.run_due()
    v, lord = await bob.village(), await alice.village()
    assert lord["economy"]["tribute_in"]["wood"] == v["economy"]["tribute_out"]["wood"] > eco["tribute_out"]["wood"]

    # the vassal's culture now radiates for the overlord
    culture = (await alice.get(f"/villages/{alice.village_id}/culture")).json()
    near = next(n for n in culture["neighbours"] if n["village"]["id"] == bob.village_id)
    assert near["your_influence"] > 0 and near["their_influence"] == 0
    area = (await alice.get("/map", params={"x": target["x"] - 3, "y": target["y"] - 3, "w": 8, "h": 8})).json()
    tile = next(m for m in area["villages"] if m["id"] == bob.village_id)
    assert tile["overlord_id"] == alice.village_id and tile["overlord_tribe"] == "clans"
    assert next(r for r in (await alice.get("/rankings")).json() if r["id"] == alice.id)["vassals"] == 1

    # the vassal rebels: one win against its overlord sets it free
    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"legionary": 200}))
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {}))
    me = await alice.village()
    report = await raid(game, bob, me, {"legionary": 50})
    assert report["submission"]["freed"]
    v, lord = await bob.village(), await alice.village()
    assert v["submission"] is None and "tribute" not in v["state"] and v["economy"]["tribute_out"] == {}
    assert lord["vassals"] == [] and lord["economy"]["tribute_in"] == {}


async def test_a_successful_defence_resets_the_count(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    target = await bob.village()
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, target["x"] + 2, target["y"])
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 500}))
    for _ in range(3):
        await raid(game, alice, target, {"clubman": 20})
    assert (await bob.village())["dominance"]["threats"][0]["wins"] == 3

    await patch_state(game, bob.village_id, lambda s: s.__setitem__("units", {"legionary": 300}))
    report = await raid(game, alice, target, {"clubman": 5})
    assert report["winner"] == "defender" and report["submission"]["reset"]
    assert (await bob.village())["dominance"]["threats"] == []


async def test_overlord_can_release_a_vassal(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    target = await bob.village()
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, target["x"] + 2, target["y"])
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 500}))
    for _ in range(5):
        await raid(game, alice, target, {"clubman": 20})
    v = await bob.village()
    assert v["submission"]["benefits"] == {"production": 0.05, "defense": 0.15, "contentment": 5.0, "trade_speed": 0.5}
    assert abs(v["state"].get("boost", 0) - 0.05) < 1e-9
    from ovian_server.repo import get_village, travel_factor

    async with game.pool.acquire() as conn:
        a, b = await get_village(conn, alice.village_id), await get_village(conn, bob.village_id)
        assert await travel_factor(game, conn, "trade", b, a, game.clock.now()) == 1 / 1.5
        assert await travel_factor(game, conn, "attack", b, a, game.clock.now()) == 1.0
    battle: dict = {}
    from ovian_server.modules.submission import ovian_battle_prepare

    async with game.tx() as tx:
        await ovian_battle_prepare(game, tx, battle, a, b)  # the overlord itself: no protection
        assert "defense_bonus" not in battle
        a.player_id = -1
        await ovian_battle_prepare(game, tx, battle, a, b)
        assert battle["defense_bonus"] == 0.15

    denied = await bob.post(f"/villages/{bob.village_id}/vassals/{bob.village_id}/release")
    assert denied.status_code in (403, 404)
    lord = (await alice.post(f"/villages/{alice.village_id}/vassals/{bob.village_id}/release")).json()
    assert lord["vassals"] == [] and lord["economy"]["tribute_in"] == {}
    freed = await bob.village()
    assert freed["submission"] is None and not freed["state"].get("boost")


async def test_voluntary_vassalage(game, register):
    from .test_society import neighbours

    alice, bob, _ = await neighbours(game, register)
    r = await bob.post(f"/villages/{bob.village_id}/fealty", {"to": alice.village_id})
    assert r.status_code == 200, r.text
    assert r.json()["fealty_offer"]["village"]["id"] == alice.village_id
    lord = await alice.village()
    assert [o["village"]["id"] for o in lord["fealty_offers"]] == [bob.village_id]
    assert (await bob.post(f"/villages/{bob.village_id}/fealty", {"to": bob.village_id})).json()["error"] == "own_city"

    r = await alice.post(f"/villages/{alice.village_id}/fealty/{bob.village_id}/accept")
    assert r.status_code == 200, r.text
    v = await bob.village()
    assert v["submission"]["voluntary"] and v["submission"]["village"]["id"] == alice.village_id
    assert v["state"]["tribute"] == 0.05
    assert "fealty_offer" not in v or not v["fealty_offer"]
    assert (await alice.village())["fealty_offers"] == []

    r = await bob.post(f"/villages/{bob.village_id}/renounce")
    assert r.status_code == 200, r.text
    v = r.json()
    assert not v["submission"] and not v["state"].get("tribute")
    assert (await bob.post(f"/villages/{bob.village_id}/renounce")).json()["error"] == "not_voluntary"

    # declined offers just go away
    await bob.post(f"/villages/{bob.village_id}/fealty", {"to": alice.village_id})
    await alice.post(f"/villages/{alice.village_id}/fealty/{bob.village_id}/decline")
    assert not (await bob.village()).get("fealty_offer")


async def test_overlord_sets_taxes(game, register):
    from ovian_server.modules.submission import submit
    from ovian_server.repo import get_village

    from .test_realm import extensions
    from .test_society import neighbours

    alice, bob, _ = await neighbours(game, register)
    with extensions(game, contentment={}):
        async with game.tx() as tx:
            lord = await get_village(tx.conn, alice.village_id, lock=True)
            vassal = await get_village(tx.conn, bob.village_id, lock=True)
            await submit(game, tx, vassal, lord)
        base = (await bob.village())["contentment"]["score"]

        # one city, heavier: tribute up, mood down (more so for being 2 tiles away)
        r = await alice.post(f"/villages/{alice.village_id}/vassals/{bob.village_id}/tax", {"rate": 0.2})
        assert r.status_code == 200, r.text
        x = r.json()["vassals"][0]["tax"]
        assert x["rate"] == 0.2 and x["source"] == "city" and x["mood"] < -10
        v = await bob.village()
        assert v["state"]["tribute"] == 0.2
        f = {f["label"]: f["value"] for f in v["contentment"]["factors"]}
        assert f["Heavy taxes"] < -10
        assert v["contentment"]["score"] < base
        assert (await alice.post(f"/villages/{alice.village_id}/vassals/{bob.village_id}/tax", {"rate": 0.9})).json()["error"] == "tax_out_of_range"

        # the realm default does not override a city's own rate, until that is cleared
        r = await alice.post("/me/vassal-tax", {"rate": 0.02})
        assert r.json() == {"default": 0.02, "vassals": 1}
        assert (await bob.village())["state"]["tribute"] == 0.2
        await alice.post(f"/villages/{alice.village_id}/vassals/{bob.village_id}/tax", {"rate": None})
        v = await bob.village()
        assert v["state"]["tribute"] == 0.02 and v["submission"]["tax"]["source"] == "realm"
        f = {f["label"]: f["value"] for f in v["contentment"]["factors"]}
        assert f["Light taxes"] == 8
