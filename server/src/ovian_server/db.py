from __future__ import annotations

import json
import logging
from importlib import resources

import asyncpg

log = logging.getLogger("ovian.db")


async def _init_connection(conn: asyncpg.Connection) -> None:
    for kind in ("json", "jsonb"):
        await conn.set_type_codec(kind, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(url, init=_init_connection, min_size=1, max_size=10)


async def migrate(pool: asyncpg.Pool, package: str = "ovian_server.migrations", table: str = "schema_migrations") -> list[str]:
    """Apply the SQL files in a migrations package in name order, once each."""
    applied: list[str] = []
    files = sorted(
        (f for f in resources.files(package).iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    async with pool.acquire() as conn:
        await conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        # Serialise concurrent server starts.
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(4242)")
            done = {r["name"] for r in await conn.fetch(f"SELECT name FROM {table}")}
            for f in files:
                if f.name in done:
                    continue
                log.info("applying migration %s", f.name)
                await conn.execute(f.read_text())
                await conn.execute(f"INSERT INTO {table}(name) VALUES ($1)", f.name)
                applied.append(f.name)
    return applied
