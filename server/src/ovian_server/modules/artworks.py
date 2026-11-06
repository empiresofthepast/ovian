"""Artworks: statues a city commissions from a famous sculptor (the *A famous sculptor* omen).

A commissioned statue becomes a find kept in the city, listed with the digs and spoils, and it always counts for the
city's culture: statues stand in the square, they need no temple room. Pack extension ``artworks``:

- ``traditions``: ``{id: {artists: [...], subjects: [...]}}``, the sculptors of an age and what they carve;
- ``by_tribe``: ``{tribe_id: tradition_id}``; ``default``: the tradition for everyone else;
- ``grades``: ``{name: {chance, culture}}``, like the archaeology grades, but a commission is never common.

The find's ``context.artwork`` carries ``{kind: statue, artist, tradition, subject, commissioned_by}``.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from .base import Module

if TYPE_CHECKING:
    from ..game import Game, Tx
    from ..repo import VillageRow

DEFAULTS: dict[str, Any] = {
    "default": "greek",
    "by_tribe": {},
    "grades": {"fine": {"chance": 0.55, "culture": 3}, "exceptional": {"chance": 0.35, "culture": 8}, "masterpiece": {"chance": 0.10, "culture": 15}},
    "traditions": {
        "greek": {"artists": ["Phidias", "Praxiteles", "Polykleitos", "Myron", "Lysippos", "Scopas"],
                  "subjects": ["Athena", "Zeus", "Apollo", "Aphrodite", "Nike", "a discus thrower", "a spear-bearer", "a charioteer"]},
    },
}


def cfg(game: Game) -> dict[str, Any]:
    c = game.content.extensions.get("artworks", {})
    return {k: c.get(k, v) for k, v in DEFAULTS.items()}


def tradition(game: Game, tribe: str) -> tuple[str, dict[str, Any]]:
    c = cfg(game)
    tid = c["by_tribe"].get(tribe) or c["default"]
    t = c["traditions"].get(tid) or next(iter(c["traditions"].values()))
    return tid, t


def grade(game: Game, rng: random.Random) -> tuple[str, float]:
    grades = cfg(game)["grades"]
    roll = rng.random() * sum(float(g.get("chance", 0)) for g in grades.values())
    for name, g in grades.items():
        roll -= float(g.get("chance", 0))
        if roll <= 0:
            return name, float(g.get("culture", 0))
    name = next(iter(grades))
    return name, float(grades[name].get("culture", 0))


async def commission(game: Game, tx: Tx, v: VillageRow, kind: str = "statue", rng: random.Random | None = None) -> dict[str, Any]:
    """Carve a statue for the (locked) city and keep it among its finds. Saves nothing."""
    from .archaeology import keep_find

    rng = rng or random.Random()
    ruler = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", v.player_id)
    tribe = await tx.conn.fetchval("SELECT tribe FROM players WHERE id = $1", v.player_id)
    tid, t = tradition(game, tribe or "")
    artist = str(rng.choice(t.get("artists") or ["an unknown master"]))
    subject = str(rng.choice(t.get("subjects") or ["the city's founder"]))
    g, culture = grade(game, rng)
    name = f"{kind.capitalize()} of {subject} by {artist}"
    context = {"world": game.settings.world_id, "pack": game.content.pack.get("id"),
               "site": {"village_id": v.id, "village": v.name, "x": v.x, "y": v.y},
               "artwork": {"kind": kind, "artist": artist, "tradition": tid, "subject": subject, "commissioned_by": ruler}}
    return await keep_find(game, tx, v, name, g, culture, context, game.clock.now(), ruler or "?")


module = Module("artworks")
