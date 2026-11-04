"""Archaeology, auxiliaries and governors."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.modules.archaeology import ancient
from ovian_server.modules.submission import release
from ovian_server.repo import get_village

from .conftest import give_buildings, patch_state, rich
from .test_embassies import bow
from .test_realm import extensions
from .test_society import neighbours


async def run_jobs(game: Game, kind: str) -> None:
    game.clock.value = await game.pool.fetchval("SELECT max(due_at) FROM jobs WHERE kind = $1", kind)
    await game.run_due()


async def test_digging_layers_and_finds(game: Game, register):
    alice, bob, _ = await neighbours(game, register)
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10, temple=3)))
    sites = (await bob.get(f"/villages/{bob.village_id}/options")).json()["free_sites"]
    a, b = sites[0], sites[1]
    # a building is raised, then pulled down: it becomes a layer of its site
    assert (await bob.post(f"/villages/{bob.village_id}/build", {"slot": a, "building": "market"})).status_code == 200
    await run_jobs(game, "build.complete")
    r = await bob.post(f"/villages/{bob.village_id}/sites/{a}/demolish")
    assert r.status_code == 200, r.text
    v = await bob.village()
    layer = v["archaeology"]["sites"][str(a)]["layers"][0]
    assert layer["building"] == "market" and layer["end"] == "demolished" and not layer["dug"] and layer["from"]

    # dig it: the market comes back as a find, kept and shown in this city's temples
    before = v["economy"]["culture"]
    wood = v["state"]["resources"]["wood"]
    r = await bob.post(f"/villages/{bob.village_id}/sites/{a}/excavate")
    assert r.status_code == 200, r.text
    assert r.json()["state"]["resources"]["wood"] < wood
    assert (await bob.post(f"/villages/{bob.village_id}/build", {"slot": a, "building": "market"})).json()["error"] == "site_busy"
    assert (await bob.post(f"/villages/{bob.village_id}/sites/{a}/excavate")).json()["error"] == "site_busy"
    await run_jobs(game, "dig.complete")
    v = await bob.village()
    finds = v["archaeology"]["finds"]
    assert len(finds) == 1
    f = finds[0]
    assert f["context"]["layer"]["building"] == "market" and f["context"]["site"]["slot"] == a
    assert f["context"]["layer"]["built_by_name"] == "bob" and f["found_by"] == "bob"
    assert f["format"] == "ovian-find/1" and f["uri"].endswith(f"/finds/{f['id']}")
    assert v["archaeology"]["display"]["shown"] == [f["id"]]
    assert abs(v["economy"]["culture"] - before - f["culture"]) < 1e-6
    report = (await bob.get("/reports")).json()[0]
    assert report["kind"] == "excavation"

    # below the known layers lies the ancient one, or bare rock; after that the site is done
    vv = await get_village(game.pool, bob.village_id)
    old = ancient(game, vv, a)
    assert (await bob.post(f"/villages/{bob.village_id}/sites/{a}/excavate")).status_code == 200
    await run_jobs(game, "dig.complete")
    v = await bob.village()
    assert len(v["archaeology"]["finds"]) == (2 if old else 1)
    if old:
        assert any(x["context"]["layer"].get("ancient") == old["id"] for x in v["archaeology"]["finds"])
    assert v["archaeology"]["sites"][str(a)]["probed"]
    assert (await bob.post(f"/villages/{bob.village_id}/sites/{a}/excavate")).json()["error"] == "nothing_left"
    # an occupied site cannot be dug; the public catalogue lists the finds without a login
    assert (await bob.post(f"/villages/{bob.village_id}/build", {"slot": b, "building": "market"})).status_code == 200
    assert (await bob.post(f"/villages/{bob.village_id}/sites/{b}/excavate")).json()["error"] == "site_busy"
    cat = (await bob.client.get("/finds")).json()
    assert cat["format"] == "ovian-find/1" and {x["id"] for x in cat["items"]} == {x["id"] for x in v["archaeology"]["finds"]}
    assert (await bob.client.get(f"/finds/{f['id']}")).json()["name"] == f["name"]
    # a find moves to another own city; alice cannot move bob's
    assert (await alice.post(f"/finds/{f['id']}/move", {"village_id": alice.village_id})).status_code == 404


async def test_ruins_are_dug_and_cleared(game: Game, register):
    alice, bob, _ = await neighbours(game, register)
    await patch_state(game, alice.village_id, rich)
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10)))
    await bow(game, bob.village_id, alice.village_id)
    q = (await bob.village())["foreign"][0]
    assert (await alice.post(f"/villages/{bob.village_id}/embassy", {"from": alice.village_id})).status_code == 200
    await run_jobs(game, "build.complete")
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="released")
    v = await bob.village()
    e = q["embassy"]
    assert v["state"]["slots"][e]["building"] == "ruin"
    assert v["archaeology"]["sites"][str(e)]["layers"][0]["building"] == "embassy"
    r = await bob.post(f"/villages/{bob.village_id}/sites/{e}/excavate")
    assert r.status_code == 200, r.text
    await run_jobs(game, "dig.complete")
    v = await bob.village()
    assert v["state"]["slots"][e]["building"] is None and v["state"]["slots"][e]["foreign"]
    f = v["archaeology"]["finds"][0]
    assert f["context"]["layer"]["building"] == "embassy" and f["context"]["layer"]["style"] == "clans"
    assert f["context"]["layer"]["built_by_name"] == "alice" and f["context"]["layer"]["end"] == "ruined"


async def test_auxiliaries_are_levied_and_desert(game: Game, register):
    with extensions(game, contentment={}):
        await _auxiliaries(game, register)


async def _auxiliaries(game: Game, register):
    alice, bob, _ = await neighbours(game, register)  # alice: clans, bob: legion
    await patch_state(game, alice.village_id, rich)
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10, barracks=5)))
    await bow(game, bob.village_id, alice.village_id)
    q = (await bob.village())["foreign"][0]
    garrison = q["lord_sites"][1]
    order = {"from": alice.village_id, "unit": "legionary", "count": 50}
    assert (await alice.post(f"/villages/{bob.village_id}/auxiliaries", order)).json()["error"] == "no_garrison"
    r = await alice.post(f"/villages/{bob.village_id}/foreign/{garrison}", {"from": alice.village_id, "building": "garrison"})
    assert r.status_code == 200, r.text
    await run_jobs(game, "build.complete")
    g = (await alice.village())["vassals"][0]["garrison"]
    assert g["capacity"] == 100 and any(o["unit"] == "legionary" for o in g["auxiliaries"]["options"])
    assert (await bob.post(f"/villages/{bob.village_id}/auxiliaries", {**order, "from": bob.village_id})).json()["error"] == "not_your_vassal"
    mood = (await bob.village())["contentment"]["score"]
    wood = (await alice.village())["state"]["resources"]["wood"]
    r = await alice.post(f"/villages/{bob.village_id}/auxiliaries", order)
    assert r.status_code == 200, r.text
    assert (await alice.village())["state"]["resources"]["wood"] < wood
    assert (await bob.village())["contentment"]["score"] < mood  # the levy angers the city
    order["count"] = 60
    assert (await alice.post(f"/villages/{bob.village_id}/auxiliaries", order)).json()["error"] == "garrison_full"
    assert (await alice.post(f"/villages/{bob.village_id}/auxiliaries", {**order, "unit": "clubman", "count": 5})).json()["error"] == "wrong_tribe"
    game.clock.value = await game.pool.fetchval("SELECT max((payload->>'finishes_at')::bigint) FROM jobs WHERE kind = 'aux.train'")
    await game.run_due()
    here = await game.pool.fetchval("SELECT units FROM stationed WHERE host_id = $1 AND home_id = $2", bob.village_id, alice.village_id)
    assert here == {"legionary": 50}
    assert (await alice.village())["vassals"][0]["garrison"]["auxiliaries"]["levied"] == 50
    # bob breaks free: the auxiliaries join him
    units = (await bob.village())["state"].get("units", {}).get("legionary", 0)
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="uprising")
    assert (await bob.village())["state"]["units"]["legionary"] == units + 50
    assert not await game.pool.fetchval("SELECT units FROM stationed WHERE host_id = $1 AND home_id = $2", bob.village_id, alice.village_id)


async def test_governors_rule_and_prefects(game: Game, register):
    with extensions(game, contentment={}):
        await _governors(game, register)


async def _governors(game: Game, register):
    alice, bob, _ = await neighbours(game, register)
    await patch_state(game, alice.village_id, rich)
    await patch_state(game, bob.village_id, lambda s: (rich(s), give_buildings(s, town_hall=10)))
    me = (await alice.get("/me/governors")).json()
    assert len(me["candidates"]) == 3 and me["max"] == 1 and all(len(c["traits"]) == 2 for c in me["candidates"])
    assert me == (await alice.get("/me/governors")).json()  # the offer stays until it is refreshed
    r = await alice.post("/me/governors", {"candidate": 0, "from": alice.village_id})
    assert r.status_code == 201, r.text
    gov = r.json()["governors"][0]
    assert gov["name"] == me["candidates"][0]["name"] and gov["village"] is None
    assert len(r.json()["candidates"]) == 2
    assert (await alice.post("/me/governors", {"candidate": 0, "from": alice.village_id})).json()["error"] == "too_many_governors"
    assert (await alice.post(f"/governors/{gov['id']}/appoint", {"village_id": bob.village_id})).json()["error"] == "not_your_city"

    # appointed at home, the governor's traits shape the city
    r = await alice.post(f"/governors/{gov['id']}/appoint", {"village_id": alice.village_id})
    assert r.status_code == 200, r.text
    await run_jobs(game, "governor.arrive")
    v = await alice.village()
    assert v["governor"]["id"] == gov["id"]
    traits = {t["id"]: t for t in v["governor"]["traits"]}
    if any(t.get("contentment") for t in traits.values()):
        assert any(f["label"].startswith(f"Governor {gov['name']}") for f in v["contentment"]["factors"])

    # over a vassal, a prefect sends the city's own governor away
    await bow(game, bob.village_id, alice.village_id)
    b = (await bob.get("/me/governors")).json()
    gb = (await bob.post("/me/governors", {"candidate": 0, "from": bob.village_id})).json()["governors"][0]
    assert (await bob.post(f"/governors/{gb['id']}/appoint", {"village_id": bob.village_id})).status_code == 200
    await run_jobs(game, "governor.arrive")
    assert (await bob.village())["governor"]["id"] == gb["id"]
    assert b["max"] == 1
    assert (await alice.post(f"/governors/{gov['id']}/appoint", {"village_id": bob.village_id})).status_code == 200
    await run_jobs(game, "governor.arrive")
    v = await bob.village()
    assert v["governor"]["id"] == gov["id"] and v["governor"]["prefect"]
    assert any(f["label"].startswith("A foreign prefect") for f in v["contentment"]["factors"])
    assert (await bob.get("/me/governors")).json()["governors"][0]["village"] is None
    assert (await bob.post(f"/governors/{gb['id']}/appoint", {"village_id": bob.village_id})).json()["error"] == "prefect_rules"
    assert (await alice.village())["governor"] is None  # the governor left alice's city

    # the city rises up: the prefect dies
    async with game.tx() as tx:
        await release(game, tx, await get_village(tx.conn, bob.village_id, lock=True), reason="uprising")
    assert (await bob.village())["governor"] is None
    assert (await alice.get("/me/governors")).json()["governors"] == []
