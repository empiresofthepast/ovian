"""Embassies: the overlord's foreign quarter, its styles, and the ruin it leaves behind."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.modules.submission import release, submit
from ovian_server.repo import get_village

from .conftest import give_buildings, patch_state, rich
from .test_society import neighbours


async def bow(game: Game, vassal_id: int, lord_id: int) -> None:
    async with game.tx() as tx:
        lord = await get_village(tx.conn, lord_id, lock=True)
        vassal = await get_village(tx.conn, vassal_id, lock=True)
        await submit(game, tx, vassal, lord)


async def finish(game: Game) -> None:
    game.clock.value = await game.pool.fetchval("SELECT max(due_at) FROM jobs WHERE kind = 'build.complete'")
    await game.run_due()


async def test_embassy_lifecycle_and_mixed_styles(game: Game, register):
    alice, bob, _ = await neighbours(game, register)  # alice: clans, bob: legion
    carol = await register("carol", "riders")
    await patch_state(game, alice.village_id, rich)
    await patch_state(game, carol.village_id, rich)
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10)))
    v = await bob.village()
    n = len(v["state"]["slots"])

    # a building founded while free keeps the owner's style
    sites = (await bob.get(f"/villages/{bob.village_id}/options")).json()["free_sites"]
    free, other = sites[0], sites[1]
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": free, "building": "temple"})
    assert r.status_code == 200, r.text
    assert r.json()["state"]["slots"][free]["style"] == "legion"

    await bow(game, bob.village_id, alice.village_id)
    v = await bob.village()
    slots = v["state"]["slots"]
    assert len(slots) == n + 4  # embassy, two overlord sites, one site of its own
    assert slots[n] == {"building": "embassy", "level": 0, "style": "clans", "foreign": True}
    assert slots[n + 3]["foreign"] and slots[n + 3]["building"] is None
    x = n + 3
    assert v["foreign"][0]["player_id"] == alice.id
    tribute = v["state"]["tribute"]

    # the vassal cannot build the embassy, but may build an exchange, in the overlord's style
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": n})
    assert r.json()["error"] == "overlord_site"
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": x, "building": "temple"})
    assert r.json()["error"] == "slot_type"
    # the overlord sites are never the vassal's
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": n + 1, "building": "exchange"})
    assert r.json()["error"] == "overlord_site"
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": x, "building": "garrison"})
    assert r.json()["error"] == "embassy_overlord_only"
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": x, "building": "exchange"})
    assert r.status_code == 200, r.text
    # new buildings in the city proper take the overlord's style too
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": other, "building": "market"})
    assert r.status_code == 200, r.text
    assert r.json()["state"]["slots"][other]["style"] == "clans"

    # the overlord pays for the embassy from its own city
    before = (await alice.village())["state"]["resources"]["wood"]
    r = await alice.post(f"/villages/{bob.village_id}/embassy", {"from": alice.village_id})
    assert r.status_code == 200, r.text
    assert r.json()["embassy"]["queued"][0]["level"] == 1
    assert (await alice.village())["state"]["resources"]["wood"] < before
    assert (await carol.post(f"/villages/{bob.village_id}/embassy", {"from": carol.village_id})).json()["error"] == "not_your_vassal"
    job = next(j for j in (await bob.village())["build_queue"] if j["slot"] == n)
    assert (await bob.delete(f"/villages/{bob.village_id}/jobs/{job['id']}")).json()["error"] == "paid_by_overlord"
    await finish(game)
    v = await bob.village()
    assert v["state"]["slots"][n]["level"] == 1 and v["state"]["slots"][x]["level"] == 1
    assert v["state"]["tribute"] < tribute  # the exchange lightens it
    assert v["exchange_relief"] > 0
    lord = await alice.village()
    assert lord["vassals"][0]["embassy"]["level"] == 1
    r = await bob.post(f"/villages/{bob.village_id}/sites/{n}/demolish")
    assert r.json()["error"] == "cannot_demolish"

    # carol takes the city: alice's embassy falls to ruin, carol opens her own quarter
    await bow(game, bob.village_id, carol.village_id)
    v = await bob.village()
    slots = v["state"]["slots"]
    assert slots[n] == {"building": "ruin", "level": 1, "style": "clans", "foreign": True}
    assert slots[x]["building"] == "exchange" and slots[x]["style"] == "clans"
    assert slots[n + 4] == {"building": "embassy", "level": 0, "style": "riders", "foreign": True}
    assert slots[free]["style"] == "legion" and slots[other]["style"] == "clans"  # nothing changes style

    # free again: carol's empty embassy site is just an empty foreign site; the ruin can be cleared
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="released")
    v = await bob.village()
    assert v["state"]["slots"][n + 4]["building"] is None and v["state"]["slots"][n + 4]["foreign"]
    r = await bob.post(f"/villages/{bob.village_id}/sites/{n}/demolish")
    assert r.status_code == 200, r.text
    assert r.json()["state"]["slots"][n] == {"building": None, "level": 0, "foreign": True}

    # alice comes back: her old embassy site is reused
    await bow(game, bob.village_id, alice.village_id)
    v = await bob.village()
    assert len(v["state"]["slots"]) == n + 8
    assert v["state"]["slots"][n]["building"] == "embassy"
    # but after the ruin was cleared, that site stays an overlord site: still not bob's
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="released")
    r = await bob.post(f"/villages/{bob.village_id}/build", {"slot": n + 5, "building": "exchange"})
    assert r.json()["error"] == "overlord_site"


async def test_cultural_exchange_and_garrison(game: Game, register):
    alice, bob, target = await neighbours(game, register)
    carol = await register("carol", "riders")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    await patch_state(game, alice.village_id, lambda s: (rich(s), s.__setitem__("units", {"clubman": 300})))
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10, temple=10)))
    await bow(game, bob.village_id, alice.village_id)
    v = await bob.village()
    q = v["foreign"][0]
    culture_site, garrison_site = q["lord_sites"]
    before = (await bob.village())["economy"]["culture"]

    r = await alice.post(f"/villages/{bob.village_id}/foreign/{culture_site}", {"from": alice.village_id, "building": "temple"})
    assert r.json()["error"] == "not_overlord_building"
    for _ in range(2):
        r = await alice.post(f"/villages/{bob.village_id}/foreign/{culture_site}", {"from": alice.village_id, "building": "cultural_exchange"})
        assert r.status_code == 200, r.text
    r = await alice.post(f"/villages/{bob.village_id}/foreign/{garrison_site}", {"from": alice.village_id, "building": "garrison"})
    assert r.status_code == 200, r.text
    await finish(game)
    v = await bob.village()
    assert abs(v["economy"]["culture"] - before * 0.9) < 0.01  # 10% goes to the overlord
    lord = await alice.village()
    assert abs(lord["state"]["culture_in"] - before * 0.1) < 0.01
    g = lord["vassals"][0]["garrison"]
    assert g["capacity"] == 100 and g["out"] == 0

    # station troops there, then set out from the garrison against carol
    r = await alice.post(f"/villages/{alice.village_id}/send", {"kind": "reinforce", "x": target["x"], "y": target["y"], "units": {"clubman": 300}})
    assert r.status_code == 200, r.text
    game.clock.value = max(m["arrives_at"] for m in r.json()["movements"]["outgoing"])
    await game.run_due()
    c = await carol.village()
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", carol.village_id, target["x"], target["y"] + 3)
    order = {"kind": "raid", "x": target["x"], "y": target["y"] + 3, "units": {"clubman": 150}, "garrison": bob.village_id}
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).json()["error"] == "garrison_full"
    order["units"] = {"clubman": 80}
    r = await alice.post(f"/villages/{alice.village_id}/send", order)
    assert r.status_code == 200, r.text
    mv = r.json()["movements"]["outgoing"][0]
    assert mv["from"]["id"] == bob.village_id
    lord = await alice.village()
    assert lord["vassals"][0]["garrison"]["out"] == 80
    assert lord["vassals"][0]["garrison"]["here"]["clubman"] == 220
    order["units"] = {"clubman": 30}
    assert (await alice.post(f"/villages/{alice.village_id}/send", order)).json()["error"] == "garrison_full"
    # the survivors come back to the garrison, not home
    for _ in range(2):
        game.clock.value = await game.pool.fetchval("SELECT max(arrives_at) FROM movements")
        await game.run_due()
    here = await game.pool.fetchval("SELECT units FROM stationed WHERE host_id = $1 AND home_id = $2", bob.village_id, alice.village_id)
    assert here["clubman"] > 220
    assert (await alice.village())["state"].get("units", {}).get("clubman", 0) == 0

    # breaking free: everything the overlord built falls to ruin, and the culture stops flowing
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="released")
    v = await bob.village()
    assert {v["state"]["slots"][i]["building"] for i in (q["embassy"], culture_site, garrison_site)} <= {"ruin", None}
    assert v["state"]["slots"][culture_site]["building"] == "ruin"
    assert not (await alice.village())["state"].get("culture_in")
