"""Scouting and the battle simulator.

Scouts are any troops sent with ``kind: scout``. They get through when they
number at least the defenders divided by ``stealth``; then they report the
target's stores, troops, reinforcements and buildings, and come home. Otherwise
they are caught and killed, and the target learns of it.

``POST /simulate`` runs the battle engine on any armies without sending anyone.
Clients can also run the same engine locally (WebAssembly ``resolveBattle``).

**Missions** send scouts to do harm instead of only looking. They must get past
``difficulty`` times as many defenders, and may need buildings at home:

- ``sabotage``: a building of the target (not its centre or a wonder) loses a level;
- ``steal``: learn a technology the target knows and your city does not;
- ``incite``: stir up a vassal city, adding ``unrest`` (it may rise against its overlord).

Configured by the content pack::

    extensions:
      scouting:
        stealth: 10
        missions:
          sabotage: { difficulty: 2, requires: { barracks: 3 } }
          steal: { difficulty: 3 }
          incite: { difficulty: 2, unrest: 40 }
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..repo import VillageRow, accrue, add_report, get_player, hosted_upkeep, save_village
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

router = APIRouter(tags=["scouting"])

MISSIONS: dict[str, dict[str, Any]] = {"sabotage": {"difficulty": 2}, "steal": {"difficulty": 3}, "incite": {"difficulty": 2, "unrest": 40}}


def missions(game: Game) -> dict[str, dict[str, Any]]:
    custom = game.content.extensions.get("scouting", {}).get("missions")
    return MISSIONS if custom is None else custom


def _levels(v: VillageRow) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in v.state["slots"]:
        if s.get("building"):
            out[s["building"]] = max(out.get(s["building"], 0), s["level"])
    return out


async def check_mission(game: Game, tx: Tx, mission: str, home: VillageRow, target: VillageRow) -> None:
    from ..errors import rule

    m = missions(game).get(mission)
    if m is None:
        raise rule("unknown_mission")
    have = _levels(home)
    for b, n in (m.get("requires") or {}).items():
        if have.get(b, 0) < n:
            name = (game.content.building(b) or {}).get("name", b)
            raise rule("requirements_not_met", f"{name} level {n} needed")
    if mission == "incite" and not target.state.get("tribute"):
        raise rule("not_a_vassal", "only vassal cities can be incited")


def _sabotage(game: Game, target: VillageRow, rng: random.Random) -> dict[str, Any] | None:
    growth = (game.content.pack["village"].get("growth") or {}).get("building")
    wonder = game.content.extensions.get("wonder", {}).get("building", "wonder")
    spots = [i for i, s in enumerate(target.state["slots"]) if s.get("building") not in (None, growth, wonder) and s["level"] >= 2]
    if not spots:
        return None
    i = rng.choice(spots)
    s = target.state["slots"][i]
    s["level"] -= 1
    return {"slot": i, "building": s["building"], "level": s["level"]}


def _steal(home: VillageRow, target: VillageRow, rng: random.Random) -> str | None:
    known = set(home.state.get("techs", []))
    new = [t for t in target.state.get("techs", []) if t not in known]
    if not new:
        return None
    t = rng.choice(new)
    home.state.setdefault("techs", []).append(t)
    return t


async def scout(game: Game, tx: Tx, m: dict[str, Any], home: VillageRow, target: VillageRow) -> None:
    from .military import back_to, dispatch
    from .villages import push_village

    at = m["arrives_at"]
    await accrue(game, tx, target, at=at)
    garrison = await tx.conn.fetch(
        "SELECT s.units, v.name, v.player_id FROM stationed s JOIN villages v ON v.id = s.home_id WHERE s.host_id = $1", target.id)
    stealth = float(game.content.extensions.get("scouting", {}).get("stealth", 10))
    defenders = sum(target.state.get("units", {}).values()) + sum(sum(g["units"].values()) for g in garrison)
    scouts = sum(m["units"].values())
    mission = m.get("mission")
    difficulty = float(missions(game).get(mission, {}).get("difficulty", 1)) if mission else 1.0
    success = scouts * stealth >= defenders * difficulty
    attacker = await get_player(tx.conn, home.player_id)
    defender = await get_player(tx.conn, target.player_id)
    base = {"kind": "scout", "at": at, "success": success, "scouts": m["units"], "mission": mission,
            "attacker": {"player": {"id": attacker["id"], "name": attacker["username"]}, "village": home.public()},
            "defender": {"player": {"id": defender["id"], "name": defender["username"]}, "village": target.public()}}
    if success and mission:
        await _mission(game, tx, m, mission, home, target, base)
        await save_village(game, tx, target)
        await push_village(game, tx, home)
        await push_village(game, tx, target)
        return
    if success:
        eco = game.engine.economy(target.state, await hosted_upkeep(game, tx.conn, target.id))
        hero = await tx.conn.fetchval("SELECT name FROM heroes WHERE village_id = $1 AND status = 'home'", target.id)
        intel = base | {
            "resources": {k: round(n) for k, n in target.state["resources"].items()},
            "capacity": eco["capacity"],
            "hidden": eco["hidden"],
            "units": target.state.get("units", {}),
            "reinforcements": [{"from": g["name"], "units": g["units"]} for g in garrison],
            "buildings": [{"building": s["building"], "level": s["level"]} for s in target.state["slots"] if s.get("building") and s["level"] > 0],
            "defense_bonus": eco["defense_bonus"],
            "population": target.population,
            "hero": hero,
        }
        await dispatch(game, tx, "return", home.player_id, home, target, await back_to(tx, m, home), m["units"], depart=at)
        await add_report(game, tx, home.player_id, "scout", f"Scouts report on {target.name}", intel)
        if defenders:
            await add_report(game, tx, target.player_id, "scout", f"Scouts from {home.name} slipped past {target.name}",
                             base | {"noticed": True})
    else:
        await add_report(game, tx, home.player_id, "scout", f"Your scouts were caught at {target.name}", base)
        await add_report(game, tx, target.player_id, "scout", f"Scouts from {home.name} caught at {target.name}", base)
    await save_village(game, tx, target)
    await push_village(game, tx, home)


async def _mission(game: Game, tx: Tx, m: dict[str, Any], mission: str, home: VillageRow, target: VillageRow, base: dict[str, Any]) -> None:
    from .military import back_to, dispatch

    rng = random.Random()
    done: dict[str, Any] = {}
    if mission == "sabotage":
        hit = _sabotage(game, target, rng)
        if hit:
            b = game.content.building(hit["building"])
            done = {"building": hit["building"], "name": b["name"] if b else hit["building"], "level": hit["level"]}
            title_a = f"Saboteurs damaged the {done['name']} of {target.name}"
            title_d = f"Saboteurs from {home.name} damaged your {done['name']} in {target.name}"
        else:
            title_a = title_d = f"Saboteurs found nothing worth burning in {target.name}"
    elif mission == "steal":
        await accrue(game, tx, home)
        t = _steal(home, target, rng)
        if t:
            tech = next((x for x in game.content.pack.get("techs", []) if x["id"] == t), {"name": t})
            done = {"tech": t, "name": tech.get("name", t)}
            await save_village(game, tx, home)
            title_a = f"Spies brought home the secret of {done['name']} from {target.name}"
            title_d = f"Spies from {home.name} stole the secret of {done['name']} from {target.name}"
        else:
            title_a = title_d = f"Spies learned nothing new in {target.name}"
    else:
        from .contentment import add_unrest, politics

        points = float(missions(game).get("incite", {}).get("unrest", 40))
        points *= politics(game, target)["agitators"]
        done = {"unrest": round(await add_unrest(game, tx, target, points), 1), "added": points}
        title_a = f"Agitators stirred up {target.name}"
        title_d = f"Agitators from {home.name} stirred up {target.name}"
    report = base | {"result": done}
    await dispatch(game, tx, "return", home.player_id, home, target, await back_to(tx, m, home), m["units"], depart=m["arrives_at"])
    await add_report(game, tx, home.player_id, "scout", title_a, report)
    await add_report(game, tx, target.player_id, "scout", title_d, report | {"noticed": True})


class Simulation(BaseModel):
    kind: Literal["attack", "raid"] = "attack"
    attackers: dict[str, int]
    defenders: dict[str, int] = Field(default_factory=dict)
    defense_bonus: float = 0.0
    attack_multiplier: float = 1.0


@router.post("/simulate")
async def simulate(body: Simulation, game: GameDep) -> dict[str, Any]:
    """Resolve a battle without sending anyone. Base defense and walls (as ``defense_bonus``) apply as in a real battle."""
    return game.engine.resolve_battle({"kind": body.kind, "attackers": body.attackers, "defenders": [body.defenders],
                                       "defense_bonus": body.defense_bonus, "attack_multiplier": body.attack_multiplier})


module = Module("scouting", router=router)
