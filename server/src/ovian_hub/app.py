"""FastAPI application of the hub. Run with ``python -m ovian_hub`` (or ``ovian-hub``)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ovian_server import __version__
from ovian_server.db import create_pool, migrate
from ovian_server.errors import GameError, game_error_handler

from . import api, patreon
from .config import HubSettings
from .hub import Hub

log = logging.getLogger("ovian.hub")


async def declare_worlds(hub: Hub) -> None:
    """OVIAN_HUB_WORLDS="id|name|api_url|internal_url;...": create the worlds listed, or update their addresses."""
    for item in (w.strip() for w in hub.settings.worlds.split(";")):
        if not item:
            continue
        parts = [p.strip() for p in item.split("|")] + ["", "", ""]
        world_id, name, api_url, internal_url = parts[:4]
        if not world_id or not api_url:
            log.warning("OVIAN_HUB_WORLDS: skipping %r (needs id|name|api_url[|internal_url])", item)
            continue
        assert hub.pool is not None
        await hub.pool.execute(
            """INSERT INTO worlds(id, name, api_url, internal_url, created_at) VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (id) DO UPDATE SET api_url = $3, internal_url = $4""",
            world_id, name or world_id, api_url, internal_url, hub.now())


def create_app(settings: HubSettings | None = None, hub: Hub | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or HubSettings()
    for name in ("jwt_secret", "world_secret"):
        if getattr(settings, name).startswith("dev-"):
            log.warning("OVIAN_HUB_%s is a development default; set a secret before going public", name.upper())
    hub = hub or Hub(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub.pool = await create_pool(settings.database_url)
        applied = await migrate(hub.pool, "ovian_hub.migrations", "hub_migrations")
        if applied:
            log.info("applied hub migrations: %s", ", ".join(applied))
        admins = [u.lower() for u in HubSettings.split(settings.admin_users)]
        if admins:
            await hub.pool.execute("UPDATE accounts SET is_admin = true WHERE lower(username) = ANY($1::text[])", admins)
        await declare_worlds(hub)
        try:
            yield
        finally:
            if hub.tasks:
                await asyncio.gather(*hub.tasks, return_exceptions=True)
            await hub.pool.close()

    app = FastAPI(title="Ovian hub API", version=__version__, lifespan=lifespan,
                  description="Accounts shared by every world, founders, badges, Patreon and the list of worlds.")
    app.state.hub = hub
    app.add_exception_handler(GameError, game_error_handler)
    origins = HubSettings.split(settings.cors_origins)
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials="*" not in origins,
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "patreon": bool(settings.patreon_client_id)}

    app.include_router(api.router, prefix="/api/v1")
    app.include_router(patreon.router, prefix="/api/v1")
    return app
