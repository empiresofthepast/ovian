"""Civil servants: a city's citizens defend it as its people's base soldiers."""

from __future__ import annotations

from ovian_server.game import Game
from ovian_server.modules import militia

from .conftest import patch_state
from .test_realm import extensions
from .test_society import arrive, last_report, neighbours


async def test_citizens_defend_their_city(game: Game, client, register):
    alice, bob, target = await neighbours(game, register)
    await patch_state(game, alice.village_id, lambda s: s.__setitem__("units", {"clubman": 40}))

    async def attack() -> dict:
        v = (await alice.post(f"/villages/{alice.village_id}/send", {"kind": "raid", "x": target["x"], "y": target["y"], "units": {"clubman": 20}})).json()
        await arrive(game, v)
        return (await last_report(bob))["data"]

    with extensions(game, militia={"techs": {"civil_servants": 1.0}}):
        unit = militia.unit_for(game, "legion")
        assert unit and game.content.unit(unit)["tribe"] == "legion"
        # without the tech nobody takes up arms
        assert "militia" not in await bob.village()
        r = await attack()
        assert "militia" not in r["defender"] and r["winner"] == "attacker"

        await patch_state(game, bob.village_id, lambda s: s.__setitem__("techs", [*s.get("techs", []), "civil_servants"]))
        v = await bob.village()
        pop = int(v["economy"]["population"])
        assert pop > 0 and v["militia"] == {unit: pop}
        r = await attack()
        assert r["defender"]["militia"]["units"] == {unit: pop}
        assert r["defense_power"] > 0
        # the citizens go back to work: the city keeps no troops it did not have
        assert unit not in (await bob.village())["state"].get("units", {})
