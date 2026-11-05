"""Citizen militia: once a city researches a militia tech, its citizens take up arms when it is attacked.

``extensions.militia``:

    militia:
      techs: { civil_servants: 1.0 }   # soldiers per citizen, for each tech (they add up)
      units: { gaul: gaul_infantry_spearman }   # optional: the people's militia unit

Citizens are the city's population (what its buildings house). They fight as the people's base soldier:
``<tribe>_infantry_spearman`` when the pack has one, else its cheapest infantry. They stand in the battle as one
more group of defenders, beside the city's own troops and the garrison, and go back to their trades afterwards:
the fallen are counted in the report, but the population, kept by the buildings, does not shrink.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..hooks import hookimpl
from ..repo import VillageRow, hosted_upkeep
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("militia") or {}


def unit_for(game: Game, tribe: str) -> str | None:
    """The people's base soldier."""
    chosen = (cfg(game).get("units") or {}).get(tribe)
    if chosen and game.content.unit(chosen):
        return chosen
    own = [u for u in game.content.pack["units"] if u.get("tribe") == tribe]
    by_name = next((u for u in own if u["id"] == f"{tribe}_infantry_spearman"), None)
    if by_name:
        return by_name["id"]
    infantry = sorted((u for u in own if u.get("class") == "infantry"), key=lambda u: (sum(u["cost"].values()), u["id"]))
    return infantry[0]["id"] if infantry else None


def per_citizen(game: Game, state: dict[str, Any]) -> float:
    techs = cfg(game).get("techs") or {}
    return sum(float(techs[t]) for t in state.get("techs", []) if t in techs)


async def militia(game: Game, conn: Any, v: VillageRow, tribe: str) -> dict[str, int]:
    """The citizens who would defend this city now, as units."""
    ratio = per_citizen(game, v.state)
    unit = unit_for(game, tribe) if ratio > 0 else None
    if not unit or v.meta.get("camp"):
        return {}
    population = game.engine.economy(v.state, await hosted_upkeep(game, conn, v.id))["population"]
    n = int(population * ratio)
    return {unit: n} if n > 0 else {}


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    if not cfg(game) or defender.player_id is None:
        return
    tribe = await tx.conn.fetchval("SELECT tribe FROM players WHERE id = $1", defender.player_id)
    units = await militia(game, tx.conn, defender, tribe)
    if units:
        battle["militia_index"] = len(battle["defenders"])
        battle["defenders"].append(units)


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    i = battle.get("militia_index")
    if i is not None and "defender" in report:
        report["defender"]["militia"] = {"units": battle["defenders"][i], "losses": result["defender_losses"][i]}


@hookimpl
async def ovian_village_view(game: Game, conn: Any, village: VillageRow, view: dict[str, Any]) -> None:
    if not cfg(game) or village.player_id is None:
        return
    tribe = await conn.fetchval("SELECT tribe FROM players WHERE id = $1", village.player_id)
    units = await militia(game, conn, village, tribe)
    if units:
        view["militia"] = units


module = Module("militia")
