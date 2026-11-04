"""Temples, universities, research and cultural prestige in battle."""

from __future__ import annotations

from ovian_server.game import Game

from .conftest import give_buildings, patch_state


async def set_culture(game: Game, village_id: int) -> None:
    """Recompute the stored culture column after editing state directly."""
    state = await game.pool.fetchval("SELECT state FROM villages WHERE id = $1", village_id)
    await game.pool.execute("UPDATE villages SET culture = $2 WHERE id = $1", village_id, game.engine.economy(state)["culture"])


async def test_research_unlocks_advanced_units(game: Game, client, register):
    alice = await register("alice", "legion")
    def setup(s):
        give_buildings(s, town_hall=5, barracks=3, university=3, warehouse=12, granary=12)
        s["resources"] = {r: 9_000 for r in s["resources"]}  # within storage, so refunds are whole

    await patch_state(game, alice.village_id, setup)
    url = f"/villages/{alice.village_id}"

    locked = await alice.post(f"{url}/train", {"unit": "guardian", "count": 1})
    assert locked.json()["error"] == "tech_missing"
    early = await alice.post(f"{url}/research", {"tech": "metallurgy"})
    assert early.json()["error"] == "tech_missing", "Philosophy comes first"

    v = (await alice.post(f"{url}/research", {"tech": "philosophy"})).json()
    assert v["research"][0]["tech"] == "philosophy"
    again = await alice.post(f"{url}/research", {"tech": "philosophy"})
    assert again.json()["error"] == "already_researched"

    game.clock.value = v["research"][0]["due_at"]
    await game.run_due()
    v = await alice.village()
    assert v["state"]["techs"] == ["philosophy"] and v["research"] == []
    assert any(e["type"] == "research.completed" for e in game.realtime.to(game.topics.player(alice.id)))

    # cancelling refunds the cost
    before = v["state"]["resources"]["iron"]
    v = (await alice.post(f"{url}/research", {"tech": "metallurgy"})).json()
    assert v["state"]["resources"]["iron"] < before
    v = (await alice.delete(f"{url}/jobs/{v['research'][0]['id']}")).json()
    assert round(v["state"]["resources"]["iron"]) == round(before)

    v = (await alice.post(f"{url}/research", {"tech": "metallurgy"})).json()
    game.clock.value = v["research"][0]["due_at"]
    await game.run_due()
    ok = await alice.post(f"{url}/train", {"unit": "guardian", "count": 1})
    assert ok.status_code == 200, ok.text


async def test_culture_gives_prestige_in_battle(game: Game, client, register):
    alice = await register("alice", "clans")
    bob = await register("bob", "legion")
    await game.pool.execute("UPDATE players SET protected_until = 0")
    target = await bob.village()
    # Alice lives two tiles from Bob and keeps a great temple and university.
    await game.pool.execute("UPDATE villages SET x = $2, y = $3 WHERE id = $1", alice.village_id, target["x"] + 2, target["y"])
    await patch_state(game, alice.village_id, lambda s: (give_buildings(s, temple=10, university=10), s.__setitem__("units", {"clubman": 40})))
    await set_culture(game, alice.village_id)

    view = (await alice.get(f"/villages/{alice.village_id}/culture")).json()
    assert view["culture"] > 50
    near = next(n for n in view["neighbours"] if n["village"]["id"] == bob.village_id)
    assert near["attack_bonus"] > 0.1 and near["their_influence"] == 0

    v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 40}})).json()
    game.clock.value = v["movements"]["outgoing"][0]["arrives_at"]
    await game.run_due()
    report_id = (await alice.get("/reports")).json()[0]["id"]
    culture = (await alice.get(f"/reports/{report_id}")).json()["data"]["culture"]
    assert culture["attacker_bonus"] > 0.1 and culture["defender_bonus"] == 0

    # the map and the rankings carry culture
    area = (await alice.get("/map", params={"x": target["x"] - 3, "y": target["y"] - 3, "w": 8, "h": 8})).json()
    assert next(m for m in area["villages"] if m["id"] == alice.village_id)["culture"] > 50
    assert not any(m["protected"] for m in area["villages"]), "protection was lifted above"
    ranks = (await alice.get("/rankings")).json()
    assert next(r for r in ranks if r["id"] == alice.id)["culture"] > 50


async def test_builders_work_in_parallel(game: Game, client, register):
    alice = await register("alice", "legion")
    url = f"/villages/{alice.village_id}/build"
    v = (await alice.post(url, {"slot": 0})).json()
    v = (await alice.post(url, {"slot": 1})).json()
    a, b = v["build_queue"]
    assert a["started_at"] == b["started_at"], "two sites are built at the same time"
    full = await alice.post(url, {"slot": 2})
    assert full.json()["error"] == "queue_full", "two builders in the village phase"
    assert v["economy"]["build_queue"] == 2

    # a city (town hall 10) has three builders, Architecture adds a fourth
    def city(s):
        give_buildings(s, town_hall=10, university=5, warehouse=12, granary=12)
        s["resources"] = {r: 9_000 for r in s["resources"]}
        s["techs"] = ["philosophy"]

    await patch_state(game, alice.village_id, city)
    v = await alice.village()
    assert v["economy"]["build_queue"] == 3
    assert (await alice.post(url, {"slot": 2})).status_code == 200
    v = (await alice.post(f"/villages/{alice.village_id}/research", {"tech": "architecture"})).json()
    game.clock.value = v["research"][0]["due_at"]
    await game.run_due()
    v = await alice.village()
    assert v["economy"]["build_queue"] == 4
    # another level of a site already under construction waits for the first
    await alice.post(url, {"slot": 5})
    v = (await alice.post(url, {"slot": 5})).json()
    first, again = [j for j in v["build_queue"] if j["slot"] == 5]
    assert again["started_at"] == first["due_at"]
