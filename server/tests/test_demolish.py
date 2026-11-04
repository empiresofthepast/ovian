"""Pulling buildings down frees the site and gives back half of what they cost."""

from __future__ import annotations

from ovian_server.game import Game

from .conftest import give_buildings, patch_state


def slot_of(v, building):
    return next(i for i, s in enumerate(v["state"]["slots"]) if s["building"] == building)


async def test_demolish(game: Game, register):
    alice = await register("alice")

    def setup(state):
        give_buildings(state, town_hall=5, warehouse=20, granary=20, barracks=3, market=2)
        state["resources"] = {r: 1000 for r in state["resources"]}

    await patch_state(game, alice.village_id, setup)
    v = await alice.village()
    market, barracks = slot_of(v, "market"), slot_of(v, "barracks")
    before = v["state"]["resources"]

    paid: dict[str, float] = {}
    for lv in (1, 2):
        for r, c in game.engine.build_cost("market", lv).items():
            paid[r] = paid.get(r, 0) + c
    r = await alice.post(f"/villages/{alice.village_id}/sites/{market}/demolish")
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["state"]["slots"][market] == {"building": None, "level": 0}
    for res, c in paid.items():
        assert abs(after["state"]["resources"][res] - before[res] - int(c * 0.5)) < 2, res

    # nothing there, a field, the town hall
    assert (await alice.post(f"/villages/{alice.village_id}/sites/{market}/demolish")).json()["error"] == "nothing_to_demolish"
    assert (await alice.post(f"/villages/{alice.village_id}/sites/0/demolish")).json()["error"] == "cannot_demolish_fields"
    th = slot_of(v, "town_hall")
    assert (await alice.post(f"/villages/{alice.village_id}/sites/{th}/demolish")).json()["error"] == "cannot_demolish"

    # a site under construction, then a barracks still training
    r = await alice.post(f"/villages/{alice.village_id}/build", {"slot": barracks})
    assert r.status_code == 200, r.text
    assert (await alice.post(f"/villages/{alice.village_id}/sites/{barracks}/demolish")).json()["error"] == "site_busy"
    job = r.json()["build_queue"][0]["id"]
    assert (await alice.delete(f"/villages/{alice.village_id}/jobs/{job}")).status_code == 200
    unit = next(u["id"] for u in game.content.pack["units"] if u["tribe"] == "clans" and u["building"] == "barracks")
    r = await alice.post(f"/villages/{alice.village_id}/train", {"unit": unit, "count": 1})
    assert r.status_code == 200, r.text
    assert (await alice.post(f"/villages/{alice.village_id}/sites/{barracks}/demolish")).json()["error"] == "building_in_use"
