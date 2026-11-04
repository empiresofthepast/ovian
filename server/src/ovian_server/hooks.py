"""Plugin hook specifications.

Everything customizable in the server goes through these hooks, including the
built-in feature modules. A plugin is any Python module or object with
functions decorated by ``@hookimpl``. See docs/modding.md.

Hooks that receive ``tx`` run inside the game transaction and may be written
as ``async def`` to use ``tx.conn``. Raising ``GameError`` aborts the action.
``ovian_modules``, ``ovian_pack_loaded`` and ``ovian_mqtt_acl`` must be sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pluggy

if TYPE_CHECKING:
    from .game import Game, Tx
    from .modules.base import Module
    from .repo import VillageRow

hookspec = pluggy.HookspecMarker("ovian")
hookimpl = pluggy.HookimplMarker("ovian")


class OvianSpec:
    @hookspec
    def ovian_modules(self) -> list[Module]:
        """Return feature modules (routes, job handlers, MQTT handlers) to mount."""

    @hookspec
    def ovian_pack_loaded(self, pack: dict[str, Any]) -> None:
        """Mutate the raw content pack before the engine validates it.

        Use it to add buildings or units from code, rebalance numbers, or
        derive data from ``pack["extensions"]``.
        """

    @hookspec
    def ovian_player_registered(self, game: Game, tx: Tx, player: dict[str, Any]) -> None:
        """Called inside the registration transaction, after the first village exists."""

    @hookspec
    def ovian_village_founded(self, game: Game, tx: Tx, village: VillageRow) -> None:
        """Called when a village is created. Mutate ``village.state`` to change it."""

    @hookspec
    def ovian_validate_order(self, game: Game, tx: Tx, player: dict[str, Any], village: VillageRow, order: dict[str, Any]) -> None:
        """Veto any player order by raising GameError.

        ``order["type"]`` is one of build, train, send, recall.
        """

    @hookspec
    def ovian_battle_prepare(self, game: Game, tx: Tx, battle: dict[str, Any], attacker: VillageRow, defender: VillageRow) -> None:
        """Adjust a battle before it is resolved.

        ``battle`` has kind, attackers, defenders, defense_bonus and
        attack_multiplier, as accepted by ``Engine.resolve_battle``.
        """

    @hookspec
    def ovian_battle_resolved(
        self, game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any], attacker: VillageRow, defender: VillageRow
    ) -> None:
        """Called after losses and loot are applied. ``report`` may be extended."""

    @hookspec
    def ovian_started(self, game: Game) -> None:
        """The server is up: database migrated, before serving. May be ``async def``."""

    @hookspec
    def ovian_build_completed(self, game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
        """A construction finished (also great-building levels raised by contributions)."""

    @hookspec
    def ovian_build_demolished(self, game: Game, tx: Tx, village: VillageRow, building: str, level: int) -> None:
        """A building of ``level`` was pulled down; its site is empty again and already saved."""

    @hookspec
    def ovian_vassal_bound(self, game: Game, tx: Tx, vassal: VillageRow, lord: VillageRow) -> None:
        """A city submitted to ``lord`` (not a colony founded by its own player); state already saved."""

    @hookspec
    def ovian_vassal_released(self, game: Game, tx: Tx, vassal: VillageRow, lord_id: int, lord_player_id: int | None, reason: str) -> None:
        """A city stopped paying tribute to ``lord_id`` (``reason``: conquered, uprising, rebellion, released, ...)."""

    @hookspec
    def ovian_boost(self, game: Game, conn: Any, village: VillageRow) -> float:
        """Return a production bonus (fraction) for a village; all results are added up.

        Call ``repo.refresh_boost`` when the inputs change, so it is settled at the right time.
        """

    @hookspec
    def ovian_production(self, game: Game, conn: Any, village: VillageRow) -> dict[str, float]:
        """Return per-resource production modifiers (fractions, may be negative); results are added up.

        Seasons and governments use it. Like ``ovian_boost``, it is applied by ``repo.refresh_boost``.
        """

    @hookspec
    def ovian_contentment(self, game: Game, conn: Any, village: VillageRow) -> list[tuple[str, float]]:
        """Return (reason, points) pairs that make a city's people happier or angrier."""

    @hookspec
    def ovian_travel(self, game: Game, conn: Any, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
        """Return a travel-time multiplier (0.8 = 20% faster) for armies, scouts and merchants (``kind`` "trade").

        All results are multiplied together.
        """

    @hookspec
    def ovian_village_view(self, game: Game, conn: Any, village: VillageRow, view: dict[str, Any]) -> None:
        """Add data to the owner's view of a village (``GET /villages/{id}`` and pushes)."""

    @hookspec(firstresult=True)
    def ovian_mqtt_acl(self, game: Game, player_id: int, topic: str, access: str) -> bool | None:
        """Decide an MQTT permission the built-in rules do not cover.

        ``access`` is "read", "write" or "subscribe". Return True or False to
        decide, None to fall through.
        """


def plugin_manager() -> pluggy.PluginManager:
    pm = pluggy.PluginManager("ovian")
    pm.add_hookspecs(OvianSpec)
    return pm
