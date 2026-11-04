"""FastAPI application factory. Run with ``python -m ovian_server``."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings
from .db import create_pool, migrate
from .errors import GameError, game_error_handler
from .game import Game

log = logging.getLogger("ovian")


def create_app(settings: Settings | None = None, game: Game | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings()
    for name in ("jwt_secret", "internal_key", "mqtt_service_password"):
        if getattr(settings, name).startswith("dev-"):
            log.warning("OVIAN_%s is a development default; set a secret before going public", name.upper())
    game = game or Game(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        game.pool = await create_pool(settings.database_url)
        applied = await migrate(game.pool)
        if applied:
            log.info("applied migrations: %s", ", ".join(applied))
        admins = [u.lower() for u in Settings.split(settings.admin_users)]
        if admins:
            await game.pool.execute("UPDATE players SET is_admin = true WHERE lower(username) = ANY($1::text[])", admins)
        await game.emit("ovian_started", game=game)
        tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(game.realtime.run(), name="realtime"),
            asyncio.create_task(game.presence.run(), name="presence"),
        ]
        if settings.scheduler_enabled:
            tasks.append(asyncio.create_task(game.run_scheduler(), name="scheduler"))
        log.info("world %s running pack %s with modules: %s", settings.world_id, game.content.pack["id"],
                 ", ".join(m.name for m in game.modules))
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await game.pool.close()

    app = FastAPI(
        title="Ovian API",
        version=__version__,
        description="REST API of an Ovian world. Realtime updates are delivered over MQTT; see GET /api/v1/realtime.",
        lifespan=lifespan,
    )
    app.state.game = game
    app.add_exception_handler(GameError, game_error_handler)
    origins = Settings.split(settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "mqtt": game.realtime.connected, "modules": [m.name for m in game.modules]}

    for m in game.modules:
        if m.router is not None:
            app.include_router(m.router, prefix=m.mount)
    return app
