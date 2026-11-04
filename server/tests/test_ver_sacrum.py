"""Ver sacrum: every 10 town hall levels found one colony, within level/2 tiles; it is yours and a vassal."""

from __future__ import annotations

import math

from ovian_server.game import Game

from .conftest import give_buildings, patch_state


def free_tile(game: Game, v: dict, near: float, far: float, taken: set) -> tuple[int, int]:
    for t in game.engine.tiles(v["x"] - 12, v["y"] - 12, 25, 25):
        d = math.hypot(t["x"] - v["x"], t["y"] - v["y"])
        if t["settleable"] and near <= d <= far and (t["x"], t["y"]) not in taken:
            return t["x"], t["y"]
    raise AssertionError("no free tile")


async def test_ver_sacrum_founds_a_managed_colony(game: Game, client, register):
    alice = await register("alice", "legion")
    url = f"/villages/{alice.village_id}/ver-sacrum"
    v = await alice.village()
    assert v["ver_sacrum"]["available"] == 0 and v["ver_sacrum"]["next_at_level"] == 10
    taken = {(r["x"], r["y"]) for r in await game.pool.fetch("SELECT x, y FROM villages")}
    x, y = free_tile(game, v, 2, 5, taken)
    assert (await alice.post(url, {"x": x, "y": y})).json()["error"] == "no_ver_sacrum"

    def town_hall_20(s):
        give_buildings(s, town_hall=20, warehouse=20, granary=20)
        s["resources"] = {r: 30_000 for r in s["resources"]}

    await patch_state(game, alice.village_id, town_hall_20)
    v = await alice.village()
    vs = v["ver_sacrum"]
    assert vs["earned"] == 2 and vs["available"] == 2 and vs["range"] == 10

    far = free_tile(game, v, 10.5, 12, taken)
    assert (await alice.post(url, {"x": far[0], "y": far[1]})).json()["error"] == "out_of_range"
    me = (v["x"], v["y"])
    assert (await alice.post(url, {"x": me[0], "y": me[1]})).json()["error"] == "tile_taken"

    v = (await alice.post(url, {"x": x, "y": y, "name": "Nova Roma"})).json()
    assert v["ver_sacrum"]["available"] == 1 and v["state"]["resources"]["wood"] < 30_000
    migration = v["ver_sacrum"]["migrations"][0]
    assert (migration["x"], migration["y"]) == (x, y)
    again = await alice.post(url, {"x": x, "y": y})
    assert again.json()["error"] == "tile_taken", "migrants already on their way"

    game.clock.value = migration["arrives_at"]
    await game.run_due()
    me = (await alice.get("/me")).json()
    colony = next(c for c in me["villages"] if c["name"] == "Nova Roma")
    assert (colony["x"], colony["y"]) == (x, y)
    assert any(e["type"] == "village.founded" for e in game.realtime.to(game.topics.player(alice.id)))

    # the colony is fully managed by alice: she can build there
    c = await alice.village(colony["id"])
    assert c["submission"]["village"]["id"] == alice.village_id and c["state"]["tribute"] == 0.1
    assert (await alice.post(f"/villages/{colony['id']}/build", {"slot": 0})).status_code == 200
    # ...and it pays tribute to its mother city
    v = await alice.village()
    assert v["vassals"][0]["village"]["id"] == colony["id"]
    assert v["economy"]["tribute_in"] and v["ver_sacrum"]["colonies"][0]["id"] == colony["id"]
    assert v["ver_sacrum"]["used"] == 1 and v["ver_sacrum"]["migrations"] == []

    # a colony can never be released by its mother city
    res = await alice.post(f"/villages/{alice.village_id}/vassals/{colony['id']}/release")
    assert res.status_code == 409 and res.json()["error"] == "colony_bound"
    v = await alice.village()
    assert v["vassals"][0]["colony"] is True
    assert (await alice.village(colony["id"]))["submission"]["colony"] is True
