"""Data access shared by modules. Engine state is stored as JSON in villages.state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import asyncpg

from .errors import forbidden, not_found

if TYPE_CHECKING:
    from .game import Game, Tx


@dataclass
class VillageRow:
    id: int
    player_id: int
    name: str
    x: int
    y: int
    state: dict[str, Any]
    population: int
    meta: dict[str, Any]

    @classmethod
    def from_record(cls, r: asyncpg.Record) -> VillageRow:
        return cls(r["id"], r["player_id"], r["name"], r["x"], r["y"], r["state"], r["population"], r["meta"])

    @property
    def point(self) -> tuple[int, int]:
        return (self.x, self.y)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "x": self.x, "y": self.y, "player_id": self.player_id}


_COLS = "id, player_id, name, x, y, state, population, meta"


async def get_village(conn: asyncpg.Connection, village_id: int, *, lock: bool = False) -> VillageRow:
    sql = f"SELECT {_COLS} FROM villages WHERE id = $1" + (" FOR UPDATE" if lock else "")
    r = await conn.fetchrow(sql, village_id)
    if r is None:
        raise not_found("village_not_found")
    return VillageRow.from_record(r)


async def own_village(conn: asyncpg.Connection, village_id: int, player_id: int, *, lock: bool = False) -> VillageRow:
    v = await get_village(conn, village_id, lock=lock)
    if v.player_id != player_id:
        raise forbidden("not_your_village")
    return v


async def lock_villages(conn: asyncpg.Connection, *ids: int) -> dict[int, VillageRow]:
    """Lock several villages in id order to avoid deadlocks. Missing ones are omitted."""
    rows = await conn.fetch(f"SELECT {_COLS} FROM villages WHERE id = ANY($1::bigint[]) ORDER BY id FOR UPDATE", list(set(ids)))
    return {r["id"]: VillageRow.from_record(r) for r in rows}


async def village_at(conn: asyncpg.Connection, x: int, y: int) -> VillageRow | None:
    r = await conn.fetchrow(f"SELECT {_COLS} FROM villages WHERE x = $1 AND y = $2", x, y)
    return VillageRow.from_record(r) if r else None


async def save_village(game: Game, tx: Tx, v: VillageRow) -> None:
    eco = game.engine.economy(v.state)
    v.population = int(eco["population"])
    await tx.conn.execute(
        "UPDATE villages SET state = $2, population = $3, name = $4, meta = $5, culture = $6 WHERE id = $1",
        v.id, v.state, v.population, v.name, v.meta, float(eco.get("culture", 0.0)),
    )
    if v.state.get("tribute"):
        await sync_tribute(game, tx, v.id, eco.get("tribute_out", {}))


def _flow_changed(a: dict[str, float], b: dict[str, float]) -> bool:
    return any(abs(a.get(k, 0.0) - b.get(k, 0.0)) > 1e-6 for k in {*a, *b})


async def sync_tribute(game: Game, tx: Tx, vassal_id: int, flow: dict[str, float]) -> None:
    """Keep a vassal's overlord receiving exactly what the vassal pays."""
    row = await tx.conn.fetchrow("SELECT overlord_id, flow FROM vassals WHERE vassal_id = $1", vassal_id)
    if row is None or not _flow_changed(row["flow"], flow):
        return
    await tx.conn.execute("UPDATE vassals SET flow = $2 WHERE vassal_id = $1", vassal_id, flow)
    await refresh_tribute_in(game, tx, row["overlord_id"])


async def refresh_tribute_in(game: Game, tx: Tx, overlord_id: int) -> VillageRow | None:
    """Settle an overlord's resources, then set its income to the sum of its vassals' tribute."""
    r = await tx.conn.fetchrow(f"SELECT {_COLS} FROM villages WHERE id = $1 FOR UPDATE", overlord_id)
    if r is None:
        return None
    lord = await accrue(game, tx, VillageRow.from_record(r))
    total: dict[str, float] = {}
    for f in await tx.conn.fetch("SELECT flow FROM vassals WHERE overlord_id = $1", overlord_id):
        for k, n in f["flow"].items():
            total[k] = total.get(k, 0.0) + n
    if total:
        lord.state["tribute_in"] = total
    else:
        lord.state.pop("tribute_in", None)
    await save_village(game, tx, lord)
    return lord


async def hosted_upkeep(game: Game, conn: asyncpg.Connection, village_id: int) -> float:
    """Upkeep of foreign troops stationed in a village; the host pays it."""
    rows = await conn.fetch("SELECT units FROM stationed WHERE host_id = $1", village_id)
    return sum(game.engine.unit_upkeep(r["units"]) for r in rows)


async def accrue(game: Game, tx: Tx, v: VillageRow, at: int | None = None) -> VillageRow:
    """Bring a (locked) village's resources up to ``at`` (default now), in place."""
    extra = await hosted_upkeep(game, tx.conn, v.id)
    v.state = game.engine.accrue(game.engine.normalize(v.state), at if at is not None else game.clock.now(), extra)
    return v


async def refresh_boost(game: Game, tx: Tx, v: VillageRow) -> None:
    """Settle a (locked) village at its old production, then apply the summed ``ovian_boost`` bonuses."""
    await accrue(game, tx, v)
    boost = sum(b or 0.0 for b in await game.emit("ovian_boost", game=game, conn=tx.conn, village=v))
    if boost:
        v.state["boost"] = boost
    else:
        v.state.pop("boost", None)
    by: dict[str, float] = {}
    for mods in await game.emit("ovian_production", game=game, conn=tx.conn, village=v):
        for k, n in (mods or {}).items():
            by[k] = by.get(k, 0.0) + n
    by = {k: round(n, 6) for k, n in by.items() if abs(n) > 1e-9}
    if by:
        v.state["boost_by"] = by
    else:
        v.state.pop("boost_by", None)


async def refresh_all(game: Game, player_id: int | None = None, tx: Tx | None = None) -> int:
    """Re-apply production modifiers to every player city (or one player's) and push the new views.

    Runs in ``tx`` when given, else in a transaction of its own.
    """
    from .modules.villages import push_village

    async def run(t: Tx) -> int:
        ids = await t.conn.fetch(
            "SELECT v.id FROM villages v JOIN players p ON p.id = v.player_id WHERE NOT p.npc AND ($1::bigint IS NULL OR v.player_id = $1) ORDER BY v.id",
            player_id)
        for r in ids:
            v = await get_village(t.conn, r["id"], lock=True)
            await refresh_boost(game, t, v)
            await save_village(game, t, v)
            await push_village(game, t, v)
        return len(ids)

    if tx is not None:
        return await run(tx)
    async with game.tx() as t:
        return await run(t)


async def travel_factor(game: Game, conn: asyncpg.Connection, kind: str, origin: VillageRow, target: VillageRow, at: int) -> float:
    """Product of the ``ovian_travel`` multipliers."""
    f = 1.0
    for m in await game.emit("ovian_travel", game=game, conn=conn, kind=kind, origin=origin, target=target, at=at):
        if m:
            f *= float(m)
    return max(0.05, f)


async def bump_stat(conn: asyncpg.Connection, player_id: int, stat: str, by: float = 1) -> float:
    """Add to a player's counter (battles won, camps beaten, ...) and return the new value."""
    return await conn.fetchval(
        """INSERT INTO player_stats(player_id, stat, value) VALUES ($1, $2, $3)
           ON CONFLICT (player_id, stat) DO UPDATE SET value = player_stats.value + EXCLUDED.value RETURNING value""",
        player_id, stat, by,
    )


async def get_player(conn: asyncpg.Connection, player_id: int, *, lock: bool = False) -> dict[str, Any]:
    sql = "SELECT id, username, tribe, created_at, protected_until, meta FROM players WHERE id = $1" + (" FOR UPDATE" if lock else "")
    r = await conn.fetchrow(sql, player_id)
    if r is None:
        raise not_found("player_not_found")
    return dict(r)


async def add_report(game: Game, tx: Tx, player_id: int, kind: str, title: str, data: dict[str, Any]) -> int:
    now = game.clock.now()
    report_id = await tx.conn.fetchval(
        "INSERT INTO reports(player_id, kind, title, data, created_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
        player_id, kind, title, data, now,
    )
    game.event(tx, player_id, "report.new", {"id": report_id, "kind": kind, "title": title, "created_at": now})
    return report_id
