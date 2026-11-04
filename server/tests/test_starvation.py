"""Troops starve, cheapest first, while the upkeep resource is empty and short."""

from __future__ import annotations

import math

from ovian_server.game import Game
from ovian_server.modules import starvation

from .conftest import patch_state


async def tick(game: Game) -> None:
    async with game.tx() as tx:
        await starvation.on_tick(game, tx, {"payload": {}})


async def test_troops_starve_cheapest_first(game: Game, register):
    alice = await register("alice")

    def hungry(state):
        state["resources"]["grain"] = 0
        state["units"] = {"clubman": 300, "axeman": 200}

    await patch_state(game, alice.village_id, hungry)
    v = await alice.village()
    s = v["starvation"]
    assert s["starving"] and s["troops"] == 500 and s["empty_at"] is None
    speed = game.content.pack["world"]["speed"]
    first = math.ceil(s["deficit"] * 0.25 / speed)

    await tick(game)
    v = await alice.village()
    assert v["state"]["units"]["clubman"] == 300 - first, v["state"]["units"]
    assert v["state"]["units"]["axeman"] == 200
    reports = (await alice.get("/reports")).json()
    assert reports[0]["kind"] == "starvation" and f"{first} troops starved" in reports[0]["title"]

    for _ in range(40):
        await tick(game)
    v = await alice.village()
    units = v["state"]["units"]
    assert "clubman" not in units, units  # the cheapest are gone first
    assert v["economy"]["production"]["grain"] >= 0 or not units
    # once the city feeds itself, nobody else dies
    before = dict(units)
    await tick(game)
    assert (await alice.village())["state"]["units"] == before


async def test_fed_city_does_not_starve(game: Game, register):
    bob = await register("bob")
    await patch_state(game, bob.village_id, lambda s: s.update(units={"clubman": 5}))
    await tick(game)
    v = await bob.village()
    assert v["state"]["units"] == {"clubman": 5}
    assert "starvation" not in v or not v["starvation"]["starving"]
