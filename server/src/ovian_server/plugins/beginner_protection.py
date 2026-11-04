"""Beginner protection: new players cannot be attacked for a while.

Configured by the content pack::

    extensions:
      beginner_protection_hours: 72

Attacking someone ends your own protection early. This plugin shows the main
extension points: reading a pack extension, a lifecycle hook and an order veto.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ovian_server.errors import rule
from ovian_server.hooks import hookimpl

if TYPE_CHECKING:
    from ovian_server.game import Game, Tx
    from ovian_server.repo import VillageRow


@hookimpl
async def ovian_player_registered(game: Game, tx: Tx, player: dict[str, Any]) -> None:
    hours = float(game.content.extensions.get("beginner_protection_hours", 0))
    if hours > 0:
        player["protected_until"] = game.clock.now() + int(hours * 3_600_000)
        await tx.conn.execute("UPDATE players SET protected_until = $2 WHERE id = $1", player["id"], player["protected_until"])


@hookimpl
async def ovian_validate_order(game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
    if order["type"] != "send" or order["kind"] not in ("attack", "raid", "scout"):
        return
    now = game.clock.now()
    until = await tx.conn.fetchval("SELECT protected_until FROM players WHERE id = $1", order["target"]["player_id"])
    if until and until > now:
        raise rule("target_protected", "this player is under beginner protection")
    if player["protected_until"] > now:
        await tx.conn.execute("UPDATE players SET protected_until = 0 WHERE id = $1", player["id"])
