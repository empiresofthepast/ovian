"""Settlers: trained in the city centre, they turn a beaten barbarian camp into a colony.

``extensions.settlers``:

    settlers:
      unit: settler        # each people's settler is <tribe>_settler (a unit in the pack, trained in the city centre)

Send settlers with an attack or a raid on a barbarian camp. When the attackers win and at least one settler
lives, one of them stays: the camp becomes a city of the attacker, a colony of the city they came from (as a
ver sacrum founds one: same tribute, bound for good). It starts as a new city does, plus every resource the camp
held: the troops leave its stores to the new city instead of carrying them home. Settlers do not fight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..repo import VillageRow, add_report, get_player, save_village

if TYPE_CHECKING:
    from ..game import Game, Tx


def cfg(game: Game) -> dict[str, Any]:
    return game.content.extensions.get("settlers") or {}


def is_settler(game: Game, unit: str) -> bool:
    suffix = cfg(game).get("unit")
    return bool(suffix) and (unit == suffix or unit.endswith("_" + str(suffix)))


def would_settle(game: Game, result: dict[str, Any]) -> bool:
    return bool(result["attacker_won"]) and any(n > 0 and is_settler(game, u) for u, n in result["attacker_survivors"].items())


async def settle(game: Game, tx: Tx, result: dict[str, Any], report: dict[str, Any], home: VillageRow, camp: VillageRow) -> bool:
    """After a won battle at a barbarian camp: a surviving settler founds a colony there. Returns True if it did."""
    from .submission import bind
    from .ver_sacrum import rules

    survivors = result["attacker_survivors"]
    settler = next((u for u, n in sorted(survivors.items()) if n > 0 and is_settler(game, u)), None)
    if settler is None or not result["attacker_won"] or home.player_id is None:
        return False
    # the settler stays; the rest go home without the camp's stores, which now belong to the new city
    m = await tx.conn.fetchrow(
        "SELECT id, units FROM movements WHERE kind = 'return' AND home_id = $1 AND from_id = $2 ORDER BY id DESC LIMIT 1 FOR UPDATE",
        home.id, camp.id)
    loot = dict(report.get("loot") or {})
    if m is not None:
        units = dict(m["units"])
        units[settler] -= 1
        units = {u: n for u, n in units.items() if n > 0}
        if units:
            await tx.conn.execute("UPDATE movements SET units = $2, loot = '{}'::jsonb WHERE id = $1", m["id"], units)
        else:
            await tx.conn.execute("DELETE FROM jobs WHERE kind = 'movement.arrive' AND (payload->>'movement_id')::bigint = $1", m["id"])
            await tx.conn.execute("DELETE FROM movements WHERE id = $1", m["id"])
    stores = dict(camp.state.get("resources") or {})
    for r, n in loot.items():
        stores[r] = stores.get(r, 0) + n
    from .pve import REGEN

    await tx.conn.execute("DELETE FROM jobs WHERE kind = $1 AND village_id = $2", REGEN, camp.id)
    player = await get_player(tx.conn, home.player_id)
    now = game.clock.now()
    camp.player_id = home.player_id
    camp.name = f"{player['username']}'s colony"[:40]
    camp.state = game.engine.create_village(now)
    res = camp.state["resources"]  # all of it, even beyond the new city's storage (it keeps what it holds)
    for r, n in stores.items():
        res[r] = res.get(r, 0) + n
    camp.meta = {"mother_id": home.id, "settled_from_camp": now}
    await tx.conn.execute("UPDATE villages SET player_id = $2, name = $3, created_at = $4 WHERE id = $1",
                          camp.id, camp.player_id, camp.name, now)
    await game.emit("ovian_village_founded", game=game, tx=tx, village=camp)
    await save_village(game, tx, camp)
    await bind(game, tx, camp, home, rules(game).tribute)
    tx.publish(game.topics.map, {"type": "map.village_changed", "at": now, "data": camp.public()})
    report["loot"] = {}
    report["settled"] = {"village": camp.public(), "unit": settler, "stores": stores}
    data = {"from": home.public(), "colony": camp.public(), "x": camp.x, "y": camp.y, "founded": True, "camp": True, "stores": stores}
    await add_report(game, tx, home.player_id, "ver_sacrum", f"Settlers from {home.name} found {camp.name} in a barbarian camp", data)
    game.event(tx, home.player_id, "village.founded", {"village": camp.public(), "mother": home.public()})
    from .chronicle import record

    await record(game, tx, "colony", f"Settlers from {home.name} took a barbarian camp and founded {camp.name}", village=camp,
                 data={"mother": home.public()})
    return True
