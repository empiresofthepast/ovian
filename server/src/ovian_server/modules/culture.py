"""Culture: influence between neighbouring cities and its prestige in battle.

Buildings with a `culture` effect (temples, universities) give a city culture
points, stored in `villages.culture`. A city's influence reaches every place
within `culture.radius` tiles, fading with distance (engine: `influence`). A
player's influence at a place is the sum over their cities.

In a battle, both sides' influence at the battlefield (the defending city) is
compared; the dominant side fights with a prestige bonus (engine: `prestige`):
the attacker as an attack multiplier, the defender as extra defense.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import asyncpg
from fastapi import APIRouter

from ..deps import GameDep
from ..hooks import hookimpl
from ..repo import own_village
from ..security import PlayerId
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

router = APIRouter(tags=["culture"])


def _radius(game: Game) -> float:
    return float(game.content.pack.get("culture", {}).get("radius", 12.0))


async def influence_at(game: Game, conn: asyncpg.Connection, player_id: int, x: int, y: int) -> float:
    """Summed influence of a player's cities at a place.

    A vassal city's culture radiates for its overlord's player, not its own.
    """
    r = _radius(game)
    rows = await conn.fetch(
        """SELECT v.x, v.y, v.culture FROM villages v
             LEFT JOIN vassals s ON s.vassal_id = v.id LEFT JOIN villages o ON o.id = s.overlord_id
           WHERE coalesce(o.player_id, v.player_id) = $1 AND v.culture > 0
             AND v.x BETWEEN $2 AND $3 AND v.y BETWEEN $4 AND $5""",
        player_id, int(x - r), int(x + r), int(y - r), int(y + r),
    )
    return sum(game.engine.influence(row["culture"], math.hypot(row["x"] - x, row["y"] - y)) for row in rows)


@router.get("/villages/{village_id}/culture")
async def culture_view(village_id: int, player_id: PlayerId, game: GameDep) -> dict[str, Any]:
    """This city's culture, and how it stands against every foreign city within reach.

    For each neighbour: `attack_bonus` is the prestige you would fight with when
    attacking it, `defense_bonus` what you would get if it attacked you.
    """
    async with game.tx() as tx:
        v = await own_village(tx.conn, village_id, player_id)
        own = await tx.conn.fetchval("SELECT culture FROM villages WHERE id = $1", v.id)
        r = _radius(game)
        rows = await tx.conn.fetch(
            """SELECT v.id, v.name, v.x, v.y, v.player_id, v.culture, v.population, p.username, p.tribe
               FROM villages v JOIN players p ON p.id = v.player_id
               WHERE v.player_id <> $1 AND v.x BETWEEN $2 AND $3 AND v.y BETWEEN $4 AND $5""",
            player_id, int(v.x - r), int(v.x + r), int(v.y - r), int(v.y + r),
        )
        mine_here = await influence_at(game, tx.conn, player_id, v.x, v.y)
        neighbours = []
        for n in rows:
            d = math.hypot(n["x"] - v.x, n["y"] - v.y)
            if d > r:
                continue
            mine_there = await influence_at(game, tx.conn, player_id, n["x"], n["y"])
            theirs_there = await influence_at(game, tx.conn, n["player_id"], n["x"], n["y"])
            theirs_here = await influence_at(game, tx.conn, n["player_id"], v.x, v.y)
            neighbours.append({
                "village": {"id": n["id"], "name": n["name"], "x": n["x"], "y": n["y"], "player_id": n["player_id"]},
                "player_name": n["username"],
                "tribe": n["tribe"],
                "culture": n["culture"],
                "distance": round(d, 2),
                "your_influence": round(mine_there, 2),
                "their_influence": round(theirs_there, 2),
                "attack_bonus": game.engine.prestige(mine_there, theirs_there),
                "defense_bonus": game.engine.prestige(mine_here, theirs_here),
            })
        neighbours.sort(key=lambda n: n["distance"])
        rules = game.content.pack.get("culture", {})
        return {
            "village_id": v.id,
            "culture": own,
            "influence_here": round(mine_here, 2),
            "radius": r,
            "prestige_max": rules.get("prestige_max", 0.25),
            "neighbours": neighbours,
        }


@hookimpl
async def ovian_battle_prepare(game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
    """The side whose culture dominates the battlefield fights with prestige."""
    x, y = defender.x, defender.y
    att = await influence_at(game, tx.conn, attacker.player_id, x, y)
    dfn = await influence_at(game, tx.conn, defender.player_id, x, y)
    a_bonus, d_bonus = game.engine.prestige(att, dfn), game.engine.prestige(dfn, att)
    if a_bonus:
        battle["attack_multiplier"] = battle.get("attack_multiplier", 1.0) * (1 + a_bonus)
    if d_bonus:
        battle["defense_bonus"] = battle.get("defense_bonus", 0.0) + d_bonus
    battle["culture"] = {"attacker_influence": round(att, 2), "defender_influence": round(dfn, 2),
                         "attacker_bonus": a_bonus, "defender_bonus": d_bonus}


@hookimpl
def ovian_battle_resolved(battle: dict[str, Any], report: dict[str, Any], **_: Any) -> None:
    if battle.get("culture"):
        report["culture"] = battle["culture"]


module = Module("culture", router=router)
