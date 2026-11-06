"""The lie of the land: a city next to mountains quarries more stone, one next to forests cuts more wood.

Pack extension ``terrain`` (defaults below): within ``radius`` tiles (a square around the city), every tile of a
terrain in ``per_tile`` adds its production bonus (a fraction), capped per resource by ``max``. The bonus joins the
other production modifiers (``ovian_production``) and shows in the village view as ``terrain``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..hooks import hookimpl
from ..repo import VillageRow, refresh_all, refresh_boost
from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx

DEFAULTS: dict[str, Any] = {
    "radius": 2,
    "per_tile": {"mountain": {"stone": 0.05}, "hills": {"stone": 0.02}, "forest": {"wood": 0.05}},
    "max": {"stone": 0.4, "wood": 0.4},
}


def cfg(game: Game) -> dict[str, Any]:
    c = game.content.extensions.get("terrain", {})
    return {k: c.get(k, v) for k, v in DEFAULTS.items()}


def around(game: Game, x: int, y: int) -> dict[str, int]:
    """How many tiles of each terrain lie within the radius of (x, y), the city's own tile left out."""
    r = int(cfg(game)["radius"])
    cache: dict[tuple[int, int, int], dict[str, int]] = game.__dict__.setdefault("_terrain_around", {})
    if (x, y, r) not in cache:
        out: dict[str, int] = {}
        for t in game.engine.tiles(x - r, y - r, 2 * r + 1, 2 * r + 1):
            if (t["x"], t["y"]) != (x, y):
                out[t["terrain"]] = out.get(t["terrain"], 0) + 1
        cache[(x, y, r)] = out
    return cache[(x, y, r)]


def bonus(game: Game, x: int, y: int) -> dict[str, float]:
    c = cfg(game)
    counts = around(game, x, y)
    out: dict[str, float] = {}
    for terrain, n in counts.items():
        for res, per in (c["per_tile"].get(terrain) or {}).items():
            out[res] = out.get(res, 0.0) + float(per) * n
    caps = c["max"]
    return {k: round(min(v, float(caps.get(k, v))), 4) for k, v in out.items() if v > 0}


@hookimpl
async def ovian_production(game: Game, conn: Any, village: VillageRow) -> dict[str, float]:
    return bonus(game, village.x, village.y)


@hookimpl
async def ovian_village_view(game: Game, conn: Any, village: VillageRow, view: dict[str, Any]) -> None:
    counts = around(game, village.x, village.y)
    view["terrain"] = {
        "radius": int(cfg(game)["radius"]),
        "around": {k: counts[k] for k in cfg(game)["per_tile"] if counts.get(k)},
        "bonus": bonus(game, village.x, village.y),
    }


@hookimpl
async def ovian_village_founded(game: Game, tx: Tx, village: VillageRow) -> None:
    await refresh_boost(game, tx, village)


@hookimpl
async def ovian_started(game: Game) -> None:
    await refresh_all(game)  # cities founded before the module, or moved, get their bonus


module = Module("terrain")
