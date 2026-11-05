"""Troop movements: attacks, raids, reinforcements and returns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from ovian_engine import compute_loot
from pydantic import BaseModel, Field

from ..deps import GameDep
from ..errors import not_found, rule
from ..repo import VillageRow, accrue, add_report, get_player, lock_villages, own_village, save_village, village_at
from ..security import PlayerId
from .base import Module
from .villages import push_village

if TYPE_CHECKING:
    from ..game import Game, Tx

ARRIVE = "movement.arrive"
router = APIRouter(tags=["military"])


def clean_units(units: dict[str, int]) -> dict[str, int]:
    out = {k: int(n) for k, n in units.items() if n}
    if any(n < 0 for n in out.values()):
        raise rule("invalid_units")
    if not out:
        raise rule("no_units")
    return out


def add_units(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, n in b.items():
        out[k] = out.get(k, 0) + n
    return {k: n for k, n in out.items() if n > 0}


def take_units(have: dict[str, int], want: dict[str, int]) -> dict[str, int]:
    out = dict(have)
    for k, n in want.items():
        if out.get(k, 0) < n:
            raise rule("not_enough_units", f"not enough {k}")
        out[k] -= n
    return {k: n for k, n in out.items() if n > 0}


async def dispatch(
    game: Game, tx: Tx, kind: str, player_id: int, home: VillageRow, origin: VillageRow, target: VillageRow,
    units: dict[str, int], loot: dict[str, float] | None = None, depart: int | None = None, hero: bool = False,
    mission: str | None = None,
) -> dict[str, Any]:
    """Create a movement and its arrival job. Units must already be removed from their source."""
    depart = depart if depart is not None else game.clock.now()
    seconds = game.engine.travel_seconds(units, origin.point, target.point) if units else None
    if hero:
        from .heroes import hero_seconds

        hs = hero_seconds(game, origin.point, target.point)
        seconds = hs if seconds is None else max(seconds, hs)
    if seconds is None:
        raise rule("no_units")
    from ..repo import travel_factor

    seconds *= await travel_factor(game, tx.conn, kind, origin, target, depart)
    arrives = depart + int(seconds * 1000)
    m = await tx.conn.fetchrow(
        """INSERT INTO movements(kind, player_id, home_id, from_id, to_id, units, loot, departs_at, arrives_at, hero, mission)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *""",
        kind, player_id, home.id, origin.id, target.id, units, loot or {}, depart, arrives, hero, mission,
    )
    await game.schedule(tx, ARRIVE, arrives, {"movement_id": m["id"]}, village_id=home.id)
    if target.player_id != player_id and kind != "return":
        data = {"id": m["id"], "kind": kind, "from": origin.public(), "to": target.public(), "arrives_at": arrives, "hero": hero}
        if kind == "reinforce":
            data["units"] = units
        game.event(tx, target.player_id, "movement.incoming", data)
    return dict(m)


HOSTILE = ("attack", "raid", "scout")


class SendOrder(BaseModel):
    kind: Literal["attack", "raid", "reinforce", "scout"]
    x: int
    y: int
    units: dict[str, int] = Field(default_factory=dict, description="Unit id to count.")
    hero: bool = Field(False, description="Your hero leads the army (attack and raid only).")
    mission: Literal["look", "sabotage", "steal", "incite"] | None = Field(
        None, description="What scouts do there: look (default), sabotage a building, steal a technology, incite a vassal to revolt.")
    garrison: int | None = Field(
        None, description="Set out from your garrison in this vassal city instead, with your troops stationed there; survivors return to it.")


@router.post("/villages/{village_id}/send")
async def send(village_id: int, order: SendOrder, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    if order.hero and order.kind not in ("attack", "raid"):
        raise rule("hero_attacks_only", "the hero leads attacks and raids")
    units = clean_units(order.units)
    if order.mission and order.kind != "scout":
        raise rule("scouts_only", "only scouts go on missions")
    mission = order.mission if order.mission and order.mission != "look" else None
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        target = await village_at(tx.conn, order.x, order.y)
        if target is None:
            raise not_found("no_village_there")
        if target.id == v.id:
            raise rule("same_village")
        if order.kind in HOSTILE and target.player_id == player_id:
            raise rule("own_village", "you cannot attack your own village")
        origin = v
        if order.garrison is not None:
            origin = await _from_garrison(game, tx, v, order.garrison, target, units, order.hero)
        else:
            await accrue(game, tx, v)  # settle production before upkeep changes
            v.state["units"] = take_units(v.state.get("units", {}), units)
        player = await get_player(tx.conn, player_id)
        seconds = game.engine.travel_seconds(units, origin.point, target.point)
        await game.emit("ovian_validate_order", 
            game=game, tx=tx, player=player, village=v,
            order={"type": "send", "kind": order.kind, "target": target.public(), "units": units, "seconds": seconds, "hero": order.hero,
                   "mission": mission},
        )
        if mission:
            from .scouting import check_mission

            await check_mission(game, tx, mission, origin, target)
        if order.hero:
            from .heroes import hero_departs

            await hero_departs(game, tx, player_id, v)
        await dispatch(game, tx, order.kind, player_id, v, origin, target, units, hero=order.hero, mission=mission)
        await save_village(game, tx, v)
        if origin is not v:
            await save_village(game, tx, origin)
            await push_village(game, tx, origin)
        await push_village(game, tx, target)  # shows up in the target's incoming list
        return await push_village(game, tx, v)


async def _from_garrison(game: Game, tx: Tx, home: VillageRow, host_id: int, target: VillageRow, units: dict[str, int], hero: bool) -> VillageRow:
    """Take troops out of the garrison in a vassal city; that city is where they set out from."""
    from .embassies import garrison_room

    if hero:
        raise rule("hero_not_in_garrison", "the hero sets out from your own cities")
    host = (await lock_villages(tx.conn, host_id)).get(host_id)
    if host is None or host.id == target.id:
        raise rule("no_garrison", "no garrison of yours there")
    cap, out = await garrison_room(game, tx.conn, host, home.player_id)
    if cap <= 0:
        raise rule("no_garrison", "you need a garrison in that vassal city")
    n = sum(units.values())
    if out + n > cap:
        raise rule("garrison_full", f"your garrison there sends at most {cap} troops at a time ({out} are already out)")
    s = await tx.conn.fetchrow("SELECT id, units FROM stationed WHERE host_id = $1 AND home_id = $2 FOR UPDATE", host.id, home.id)
    if s is None:
        raise rule("not_enough_units", "station troops there first (reinforce the city)")
    await accrue(game, tx, host)  # its upkeep of foreign troops changes
    left = take_units(dict(s["units"]), units)
    if left:
        await tx.conn.execute("UPDATE stationed SET units = $2 WHERE id = $1", s["id"], left)
    else:
        await tx.conn.execute("DELETE FROM stationed WHERE id = $1", s["id"])
    return host


async def back_to(tx: Tx, m: dict[str, Any], home: VillageRow) -> VillageRow:
    """Where survivors go back to: the garrison they set out from, or home."""
    if m.get("from_id") and m["from_id"] != home.id:
        from ..repo import get_village

        try:
            host = await get_village(tx.conn, m["from_id"])
        except Exception:  # noqa: BLE001 - the city is gone
            return home
        if await tx.conn.fetchval("SELECT 1 FROM vassals s JOIN villages o ON o.id = s.overlord_id WHERE s.vassal_id = $1 AND o.player_id = $2",
                                  host.id, home.player_id):
            return host
    return home


async def _send_home(game: GameDep, player_id: int, village_id: int, stationed_id: int, as_host: bool) -> dict[str, Any]:
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id, lock=True)
        col = "host_id" if as_host else "home_id"
        s = await tx.conn.fetchrow(f"SELECT * FROM stationed WHERE id = $1 AND {col} = $2 FOR UPDATE", stationed_id, v.id)
        if s is None:
            raise not_found("reinforcement_not_found")
        vs = await lock_villages(tx.conn, s["host_id"], s["home_id"])
        host, home = vs[s["host_id"]], vs[s["home_id"]]
        player = await get_player(tx.conn, player_id)
        await game.emit("ovian_validate_order", game=game, tx=tx, player=player, village=v, order={"type": "recall", "stationed_id": stationed_id})
        await accrue(game, tx, host)
        await tx.conn.execute("DELETE FROM stationed WHERE id = $1", stationed_id)
        await dispatch(game, tx, "return", home.player_id, home, host, home, s["units"])
        await save_village(game, tx, host)
        await push_village(game, tx, host if v.id == home.id else home)
        return await push_village(game, tx, v)


@router.post("/villages/{village_id}/reinforcements/{stationed_id}/recall")
async def recall(village_id: int, stationed_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Call your troops back from another village."""
    return await _send_home(game, player_id, village_id, stationed_id, as_host=False)


@router.post("/villages/{village_id}/reinforcements/{stationed_id}/dismiss")
async def dismiss(village_id: int, stationed_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """Send foreign troops stationed in your village back home."""
    return await _send_home(game, player_id, village_id, stationed_id, as_host=True)


# ---------------------------------------------------------------- arrivals


async def on_arrive(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    m = await tx.conn.fetchrow("SELECT * FROM movements WHERE id = $1 FOR UPDATE", job["payload"]["movement_id"])
    if m is None:
        return
    m = dict(m)
    vs = await lock_villages(tx.conn, m["home_id"], m["to_id"], m["from_id"])
    home, target = vs.get(m["home_id"]), vs.get(m["to_id"])
    await tx.conn.execute("DELETE FROM movements WHERE id = $1", m["id"])
    if home is None:
        return  # the troops have nowhere to go back to
    if m["kind"] == "return" or target is None:
        await _return(game, tx, m, home)
    elif m["kind"] == "reinforce":
        await _reinforce(game, tx, m, home, target)
    elif m["kind"] == "scout":
        from .scouting import scout

        await scout(game, tx, m, home, target)
    else:
        await _battle(game, tx, m, home, target)


async def _return(game: Game, tx: Tx, m: dict[str, Any], home: VillageRow) -> None:
    if m["to_id"] != home.id:  # back to a garrison: the troops stay there, the loot goes home
        await tx.conn.execute(
            """INSERT INTO stationed(host_id, home_id, units) VALUES ($1, $2, $3)
               ON CONFLICT (host_id, home_id) DO UPDATE SET units = (
                 SELECT jsonb_object_agg(k, v) FROM (
                   SELECT key AS k, sum(value::bigint) AS v
                   FROM (SELECT * FROM jsonb_each_text(stationed.units) UNION ALL SELECT * FROM jsonb_each_text(EXCLUDED.units)) u
                   GROUP BY key) s)""",
            m["to_id"], home.id, m["units"],
        )
        m = m | {"units": {}}
    await accrue(game, tx, home, at=m["arrives_at"])
    home.state["units"] = add_units(home.state.get("units", {}), m["units"])
    if m["loot"]:
        home.state = game.engine.deposit(home.state, m["loot"])
    await save_village(game, tx, home)
    if m.get("hero"):
        from .heroes import hero_returns

        await hero_returns(game, tx, home)
    game.event(tx, home.player_id, "movement.returned", {"village_id": home.id, "units": m["units"], "loot": m["loot"], "hero": m.get("hero", False)})
    await push_village(game, tx, home)


async def _reinforce(game: Game, tx: Tx, m: dict[str, Any], home: VillageRow, target: VillageRow) -> None:
    await accrue(game, tx, target, at=m["arrives_at"])
    await tx.conn.execute(
        """INSERT INTO stationed(host_id, home_id, units) VALUES ($1, $2, $3)
           ON CONFLICT (host_id, home_id) DO UPDATE SET units = (
             SELECT jsonb_object_agg(k, v) FROM (
               SELECT key AS k, sum(value::bigint) AS v
               FROM (SELECT * FROM jsonb_each_text(stationed.units) UNION ALL SELECT * FROM jsonb_each_text(EXCLUDED.units)) u
               GROUP BY key) s)""",
        target.id, home.id, m["units"],
    )
    await save_village(game, tx, target)
    data = {"from": home.public(), "to": target.public(), "units": m["units"]}
    await add_report(game, tx, home.player_id, "reinforcement", f"Reinforcement reached {target.name}", data)
    if target.player_id != home.player_id:
        await add_report(game, tx, target.player_id, "reinforcement", f"Reinforcement from {home.name} arrived", data)
    await push_village(game, tx, target)
    if target.player_id != home.player_id:
        await push_village(game, tx, home)


async def _battle(game: Game, tx: Tx, m: dict[str, Any], home: VillageRow, target: VillageRow) -> None:
    at = m["arrives_at"]
    await accrue(game, tx, target, at=at)
    garrison = await tx.conn.fetch(
        "SELECT s.*, v.player_id, v.name FROM stationed s JOIN villages v ON v.id = s.home_id WHERE s.host_id = $1 ORDER BY s.id FOR UPDATE OF s",
        target.id,
    )
    from ..repo import hosted_upkeep

    eco = game.engine.economy(target.state, await hosted_upkeep(game, tx.conn, target.id))
    battle = {
        "kind": m["kind"],
        "attackers": m["units"],
        "defenders": [target.state.get("units", {}), *[g["units"] for g in garrison]],
        "defense_bonus": eco["defense_bonus"],
        "attack_multiplier": 1.0,
        "hero": m["hero"],
        "at": at,
        "mission": m.get("mission"),
    }
    await game.emit("ovian_battle_prepare", game=game, tx=tx, battle=battle, attacker=home, defender=target)
    engine_battle = {k: battle[k] for k in ("kind", "attackers", "defenders", "defense_bonus", "attack_multiplier")}
    result = game.engine.resolve_battle(engine_battle)

    target.state["units"] = result["defender_survivors"][0]
    for g, survivors in zip(garrison, result["defender_survivors"][1:]):
        if survivors:
            await tx.conn.execute("UPDATE stationed SET units = $2 WHERE id = $1", g["id"], survivors)
        else:
            await tx.conn.execute("DELETE FROM stationed WHERE id = $1", g["id"])

    survivors = result["attacker_survivors"]
    loot: dict[str, float] = {}
    if survivors:
        loot = compute_loot(target.state["resources"], game.engine.carry_capacity(survivors), eco["hidden"])
        for r, n in loot.items():
            target.state["resources"][r] -= n
        await dispatch(game, tx, "return", home.player_id, home, target, await back_to(tx, m, home), survivors, loot=loot, depart=at, hero=m["hero"])
    await save_village(game, tx, target)

    attacker_player = await get_player(tx.conn, home.player_id)
    defender_player = await get_player(tx.conn, target.player_id)
    report = {
        "kind": m["kind"],
        "at": at,
        "winner": "attacker" if result["attacker_won"] else "defender",
        "attacker": {"player": {"id": attacker_player["id"], "name": attacker_player["username"]}, "village": home.public(),
                     "units": m["units"], "losses": result["attacker_losses"]},
        "defender": {"player": {"id": defender_player["id"], "name": defender_player["username"]}, "village": target.public(),
                     "units": battle["defenders"][0], "losses": result["defender_losses"][0],
                     "reinforcements": [{"village": {"id": g["home_id"], "name": g["name"], "player_id": g["player_id"]},
                                         "units": battle["defenders"][i + 1], "losses": result["defender_losses"][i + 1]}
                                        for i, g in enumerate(garrison)]},
        "loot": loot,
        "attack_power": result["attack_power"],
        "defense_power": result["defense_power"],
        "defense_bonus": battle["defense_bonus"],
    }
    defender_id = target.player_id  # settlers may make the target the attacker's own city
    await game.emit("ovian_battle_resolved", game=game, tx=tx, battle=battle, result=result, report=report, attacker=home, defender=target)
    for then in battle.get("then", []):  # work a hook leaves for after every hook has seen the battle (settlers)
        await then()
    verb = "attacks" if m["kind"] == "attack" else "raids"
    title = f"{home.name} {verb} {target.name}"
    await add_report(game, tx, home.player_id, "battle", title + (" (won)" if result["attacker_won"] else " (lost)"), report)
    await add_report(game, tx, defender_id, "battle", title + (" (defended)" if not result["attacker_won"] else " (lost)"), report)
    for owner in {g["player_id"] for g in garrison} - {defender_id, home.player_id}:
        await add_report(game, tx, owner, "battle", f"Your troops fought in {target.name}", report)
    await push_village(game, tx, target)
    await push_village(game, tx, home)


module = Module("military", router=router, jobs={ARRIVE: on_arrive})
