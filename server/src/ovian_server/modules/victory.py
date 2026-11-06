"""Ways to win a world. The first player to reach any of them wins it, and the round goes to the hall of fame.

Pack extension ``victory.conditions`` (defaults below; ``false`` turns one off):

- ``wonder``: finish the last level of the wonder (``player_rules``);
- ``conquest {cities}``: hold that many cities;
- ``battles {wins}``: win that many battles against other players, attacking or defending (camps and the horde
  don't count), kept as the ``pvp_wins`` stat;
- ``culture {points}``: the culture points of all one's cities together.

AI rulers (bots) never win. ``GET /world/victory`` lists the conditions with the leaders of each race; the winner
carries the ``condition`` that won it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..hooks import hookimpl
from ..repo import VillageRow, bump_stat
from .base import Module

if TYPE_CHECKING:
    import asyncpg

    from ..game import Game, Tx

CHECK = "victory.check"
EVERY_MS = 10 * 60_000
DEFAULTS: dict[str, Any] = {
    "wonder": {"name": "Wonder"},
    "conquest": {"name": "Conquest", "cities": 20},
    "battles": {"name": "Warlord", "wins": 1000},
    "culture": {"name": "Cultural hegemony", "points": 3000},
}
TARGET = {"conquest": "cities", "battles": "wins", "culture": "points"}
VERB = {"wonder": "built the wonder", "conquest": "rules {value} cities", "battles": "won {value} battles",
        "culture": "spread {value} culture"}


def conditions(game: Game) -> dict[str, dict[str, Any]]:
    given = game.content.extensions.get("victory", {}).get("conditions", {})
    out = {}
    for k, d in DEFAULTS.items():
        c = given.get(k, {})
        if c is False:
            continue
        out[k] = {**d, **(c or {})}
    return out


_ELIGIBLE = "NOT p.npc AND NOT p.bot"
STANDINGS = {
    "conquest": f"""SELECT p.id, p.username AS name, count(v.id)::float AS value FROM players p JOIN villages v ON v.player_id = p.id
                    WHERE {_ELIGIBLE} GROUP BY p.id ORDER BY value DESC, p.id LIMIT $1""",
    "battles": f"""SELECT p.id, p.username AS name, s.value::float AS value FROM players p JOIN player_stats s ON s.player_id = p.id AND s.stat = 'pvp_wins'
                   WHERE {_ELIGIBLE} ORDER BY value DESC, p.id LIMIT $1""",
    "culture": f"""SELECT p.id, p.username AS name, coalesce(sum(v.culture), 0)::float AS value FROM players p JOIN villages v ON v.player_id = p.id
                   WHERE {_ELIGIBLE} GROUP BY p.id ORDER BY value DESC, p.id LIMIT $1""",
}


async def standings(conn: asyncpg.Connection, kind: str, limit: int = 5) -> list[dict[str, Any]]:
    return [{"player": {"id": r["id"], "name": r["name"]}, "value": round(r["value"], 1)} for r in await conn.fetch(STANDINGS[kind], limit)]


TITLES: list[dict[str, Any]] = [
    {"id": "sprawling", "name": "The most spread-out empire", "unit": "tiles from its heart, on average"},
    {"id": "compact", "name": "The most compact empire", "unit": "tiles from its heart, on average"},
    {"id": "conquest", "name": "The most cities", "unit": "cities", "skip_if": "conquest"},
    {"id": "culture", "name": "The most cultured", "unit": "culture", "skip_if": "culture"},
    {"id": "battles", "name": "The most warfaring", "unit": "battles won", "skip_if": "battles"},
]
MIN_CITIES_FOR_SHAPE = 3


async def titles(conn: asyncpg.Connection, winner: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Titles for the shape and deeds of the empires, given when the round ends (and shown as a race until then).

    The sprawling and compact empires are measured by the average distance of a player's cities from their centre
    (players with at least three cities); the race that won the world gives no title of its own.
    """
    won_by = ((winner or {}).get("condition") or {}).get("id") or ("wonder" if winner else None)
    shapes = await conn.fetch(
        f"""WITH c AS (SELECT p.id, p.username, v.x, v.y, avg(v.x) OVER w AS cx, avg(v.y) OVER w AS cy, count(*) OVER w AS n
                       FROM players p JOIN villages v ON v.player_id = p.id WHERE {_ELIGIBLE} WINDOW w AS (PARTITION BY p.id))
            SELECT id, username AS name, avg(sqrt((x - cx) ^ 2 + (y - cy) ^ 2))::float AS value FROM c
            WHERE n >= $1 GROUP BY id, username""", MIN_CITIES_FOR_SHAPE)
    out = []
    for t in TITLES:
        if t.get("skip_if") and t["skip_if"] == won_by:
            continue
        if t["id"] in ("sprawling", "compact"):
            if not shapes:
                continue
            r = (max if t["id"] == "sprawling" else min)(shapes, key=lambda r: (r["value"], -r["id"]) if t["id"] == "sprawling" else (r["value"], r["id"]))
            best = {"player": {"id": r["id"], "name": r["name"]}, "value": round(r["value"], 1)}
        else:
            top = await standings(conn, t["id"], 1)
            if not top or top[0]["value"] <= 0:
                continue
            best = top[0]
        out.append({"id": t["id"], "name": t["name"], "unit": t["unit"], **best})
    return out


async def declare(game: Game, tx: Tx, player_id: int, kind: str, value: float | None = None, village: VillageRow | None = None) -> bool:
    """Make the player the winner of the world, unless someone already won. Returns whether they won now."""
    from .chronicle import record

    c = conditions(game).get(kind)
    if c is None or await tx.conn.fetchval("SELECT 1 FROM world_state WHERE key = 'winner'"):
        return False
    name = await tx.conn.fetchval("SELECT username FROM players WHERE id = $1", player_id)
    cond = {"id": kind, "name": c["name"]}
    if kind in TARGET:
        cond |= {"value": value, "target": c[TARGET[kind]]}
    win = {"player": {"id": player_id, "name": name}, "village": village.public() if village else None, "at": game.clock.now(),
           "condition": cond, "text": f"{name} " + VERB[kind].format(value=f"{value:g}" if value is not None else "")}
    await tx.conn.execute("INSERT INTO world_state(key, value) VALUES ('winner', $1)", win)
    tx.publish(game.topics.server, {"type": "world.won", "at": game.clock.now(), "data": win})
    await record(game, tx, "victory", f"{win['text']} and won the world ({c['name']})", village=village, player_id=player_id,
                 data={"condition": cond})
    return True


async def check(game: Game, tx: Tx) -> bool:
    """Look for a player past any target; the one furthest past it (in fractions of the target) wins."""
    if await tx.conn.fetchval("SELECT 1 FROM world_state WHERE key = 'winner'"):
        return False
    best: tuple[float, int, str, float] | None = None
    for kind, c in conditions(game).items():
        if kind not in TARGET:
            continue
        target = float(c[TARGET[kind]])
        top = await standings(tx.conn, kind, 1)
        if top and target > 0 and top[0]["value"] >= target:
            score = top[0]["value"] / target
            if best is None or score > best[0]:
                best = (score, top[0]["player"]["id"], kind, top[0]["value"])
    return bool(best) and await declare(game, tx, best[1], best[2], best[3])


async def on_check(game: Game, tx: Tx, job: dict[str, Any]) -> None:
    await check(game, tx)
    await game.schedule(tx, CHECK, game.clock.now() + EVERY_MS, {})


@hookimpl
async def ovian_battle_resolved(game: Game, tx: Tx, battle: dict[str, Any], result: dict[str, Any], report: dict[str, Any],
                                attacker: VillageRow, defender: VillageRow) -> None:
    winner = attacker.player_id if report.get("winner") == "attacker" else defender.player_id
    loser = defender.player_id if winner == attacker.player_id else attacker.player_id
    if winner is None or loser is None or winner == loser or battle.get("mission") == "horde":
        return
    if await tx.conn.fetchval("SELECT npc FROM players WHERE id = $1", loser) is not False:
        return
    await bump_stat(tx.conn, winner, "pvp_wins")
    await check(game, tx)


@hookimpl
async def ovian_started(game: Game) -> None:
    async with game.tx() as tx:
        if not await tx.conn.fetchval("SELECT 1 FROM jobs WHERE kind = $1", CHECK):
            await game.schedule(tx, CHECK, game.clock.now() + EVERY_MS, {})


module = Module("victory", jobs={CHECK: on_check})
