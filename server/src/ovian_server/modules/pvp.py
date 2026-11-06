"""Player against player, or not: ``extensions.pvp.enabled`` (default true).

With ``enabled: false`` (a PvE world) attacks, raids and scouting against another player's city are refused
(``pve_world``); barbarian camps, ruins and the horde are fair game as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import rule
from ..hooks import hookimpl
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

HOSTILE = ("attack", "raid", "scout")


def enabled(game: Game) -> bool:
    return bool(game.content.extensions.get("pvp", {}).get("enabled", True))


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    if enabled(game) or order.get("type") != "send" or order.get("kind") not in HOSTILE:
        return
    target_player = (order.get("target") or {}).get("player_id")
    if not target_player or target_player == player["id"]:
        return
    if await tx.conn.fetchval("SELECT npc FROM players WHERE id = $1", target_player) is False:
        raise rule("pve_world", "this world knows no war between players: only the barbarians can be attacked")


module = Module("pvp")
