"""The world spawner: creates and stops Ovian worlds on this machine, for the hub's administrators.

The only service with write access to Docker. It does one thing: run ``docker-compose.world.yml`` for a world whose
configuration it validated and wrote itself (``worlds/<id>.env`` with fresh secrets, ``worlds/<id>.yaml`` with the
overrides onto the pack), after creating the world's database. Nothing from a request reaches a shell: ids and packs
are matched against strict patterns, and the compose command is a fixed argument list. Callers need ``X-Spawner-Key``
(``OVIAN_SPAWNER_KEY``, shared with the hub); the service is not published outside the Docker network.

- ``GET /worlds``: the spawned worlds and the state of their containers;
- ``POST /worlds``: create and start one (``{id, pack, speed, overrides, local_registration}``);
- ``POST /worlds/{id}/stop`` and ``/start``: stop and start its containers (the database stays).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

KEY = os.environ.get("OVIAN_SPAWNER_KEY", "")
REPO = Path(os.environ.get("OVIAN_REPO_DIR", "/srv/ovian"))
WORLDS = REPO / "worlds"
COMPOSE = REPO / "docker-compose.world.yml"
DB_URL = os.environ.get("OVIAN_SPAWNER_DATABASE_URL", "postgresql://ovian:ovian@db:5432/postgres")
PUBLIC_ORIGIN = os.environ.get("OVIAN_SPAWNER_PUBLIC_ORIGIN", "http://localhost:47174").rstrip("/")
WORLD_ID = r"^[a-z][a-z0-9_-]{0,30}$"
PACK_ID = r"^[a-z][a-z0-9_-]{0,40}$"
ALLOWED_OVERRIDES = {"world", "extensions"}

app = FastAPI(title="Ovian world spawner", docs_url=None, redoc_url=None)


def authorised(x_spawner_key: str = Header("")) -> None:
    if not KEY or not secrets.compare_digest(x_spawner_key, KEY):
        raise HTTPException(403, "bad spawner key")


class Spawn(BaseModel):
    id: str = Field(pattern=WORLD_ID)
    pack: str = Field("antiquity", pattern=PACK_ID)
    speed: float = Field(1.0, gt=0, le=1000)
    # {world: {...}, extensions: {...}}: merged onto the pack when the world's server starts.
    overrides: dict[str, Any] = Field(default_factory=dict)
    # True: the world has its own sign-up page besides the hub.
    local_registration: bool = False


def env_path(world_id: str) -> Path:
    return WORLDS / f"{world_id}.env"


def overrides_path(world_id: str) -> Path:
    return WORLDS / f"{world_id}.yaml"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


async def compose(world_id: str, *args: str) -> tuple[int, str]:
    cmd = ["docker", "compose", "-p", f"ovian-{world_id}", "--env-file", str(env_path(world_id)), "-f", str(COMPOSE), *args]
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=REPO, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
    return proc.returncode or 0, out.decode(errors="replace")


async def containers(world_id: str) -> list[dict[str, Any]]:
    code, out = await compose(world_id, "ps", "-a", "--format", "json")
    if code != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():  # one JSON object per line (compose v2.21+), or one array
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        data = json.loads(line)
        rows.extend(data if isinstance(data, list) else [data])
    return [{"service": r.get("Service"), "state": r.get("State"), "status": r.get("Status"), "image": r.get("Image")} for r in rows]


def summary(world_id: str, env: dict[str, str], cs: list[dict[str, Any]]) -> dict[str, Any]:
    states = {c["state"] for c in cs}
    state = "running" if cs and states == {"running"} else "stopped" if cs and "running" not in states else "partial" if cs else "absent"
    return {"id": world_id, "pack": env.get("OVIAN_PACK", ""), "speed": float(env.get("OVIAN_WORLD_SPEED", 1) or 1),
            "database": env.get("OVIAN_DATABASE_NAME", ""), "api_url": f"/w/{world_id}", "internal_url": f"http://server-{world_id}:8000",
            "mqtt_url": env.get("OVIAN_MQTT_PUBLIC_URL", ""), "state": state, "containers": cs,
            "overrides": yaml.safe_load(overrides_path(world_id).read_text()) if overrides_path(world_id).exists() else {}}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/worlds", dependencies=[Depends(authorised)])
async def list_worlds() -> list[dict[str, Any]]:
    out = []
    for p in sorted(WORLDS.glob("*.env")):
        if p.name == "example.env":
            continue
        wid = p.stem
        if not re.match(WORLD_ID, wid):
            continue
        out.append(summary(wid, read_env(p), await containers(wid)))
    return out


@app.get("/worlds/{world_id}", dependencies=[Depends(authorised)])
async def get_world(world_id: str) -> dict[str, Any]:
    if not re.match(WORLD_ID, world_id) or not env_path(world_id).exists():
        raise HTTPException(404, "unknown world")
    return summary(world_id, read_env(env_path(world_id)), await containers(world_id))


async def create_database(name: str) -> None:
    conn = await asyncpg.connect(DB_URL)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')  # name comes from WORLD_ID: letters, digits, _ and -
    finally:
        await conn.close()


@app.post("/worlds", dependencies=[Depends(authorised)], status_code=201)
async def spawn(body: Spawn) -> dict[str, Any]:
    if body.id == "example" or env_path(body.id).exists():
        raise HTTPException(409, "a world with that id exists here already")
    if not (REPO / "content" / body.pack / "pack.yaml").exists():
        raise HTTPException(422, f"no content pack '{body.pack}'")
    unknown = set(body.overrides) - ALLOWED_OVERRIDES
    if unknown:
        raise HTTPException(422, f"only world and extensions can be overridden, not {sorted(unknown)}")
    if any(not isinstance(v, dict) for v in body.overrides.values()):
        raise HTTPException(422, "world and extensions must be mappings")
    ws = PUBLIC_ORIGIN.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    db = f"ovian_{body.id}".replace("-", "_")
    env = {
        "OVIAN_WORLD_ID": body.id, "OVIAN_DATABASE_NAME": db, "OVIAN_PACK": body.pack, "OVIAN_WORLD_SPEED": f"{body.speed:g}",
        "OVIAN_MQTT_PUBLIC_URL": f"{ws}/w/{body.id}/mqtt",
        "OVIAN_JWT_SECRET": secrets.token_urlsafe(48), "OVIAN_INTERNAL_KEY": secrets.token_urlsafe(32),
        "OVIAN_MQTT_SERVICE_PASSWORD": secrets.token_urlsafe(32),
        "OVIAN_HUB_WORLD_SECRET": os.environ.get("OVIAN_HUB_WORLD_SECRET", ""),
        "OVIAN_HUB_INTERNAL_URL": os.environ.get("OVIAN_HUB_INTERNAL_URL", "http://hub:8000"),
        "OVIAN_MAIN_NETWORK": os.environ.get("OVIAN_MAIN_NETWORK", "ovian_default"),
        "OVIAN_REPO_DIR": str(REPO),
        "OVIAN_ADMIN_USERS": os.environ.get("OVIAN_SPAWNER_ADMIN_USERS", ""),
        "OVIAN_LOCAL_REGISTRATION": "true" if body.local_registration else "false",
        "OVIAN_OVERRIDES_FILE": f"/app/worlds/{body.id}.yaml" if body.overrides else "",
    }
    WORLDS.mkdir(exist_ok=True)
    if body.overrides:
        overrides_path(body.id).write_text(yaml.safe_dump(body.overrides, sort_keys=False, allow_unicode=True))
    env_path(body.id).write_text(f"# Spawned by the hub. Secrets are this world's own; do not commit.\n" + "".join(f"{k}={v}\n" for k, v in env.items()))
    try:
        await create_database(db)
        code, out = await compose(body.id, "up", "-d")
    except Exception as e:  # noqa: BLE001 - report, keep the files for a retry by hand
        raise HTTPException(502, f"could not start the world: {e}") from e
    if code != 0:
        raise HTTPException(502, f"docker compose failed:\n{out[-2000:]}")
    return summary(body.id, env, await containers(body.id))


@app.post("/worlds/{world_id}/stop", dependencies=[Depends(authorised)])
async def stop(world_id: str) -> dict[str, Any]:
    return await _lifecycle(world_id, "stop")


@app.post("/worlds/{world_id}/start", dependencies=[Depends(authorised)])
async def start(world_id: str) -> dict[str, Any]:
    return await _lifecycle(world_id, "start")


async def _lifecycle(world_id: str, verb: str) -> dict[str, Any]:
    if not re.match(WORLD_ID, world_id) or not env_path(world_id).exists():
        raise HTTPException(404, "unknown world")
    code, out = await compose(world_id, verb)
    if code != 0:
        raise HTTPException(502, f"docker compose {verb} failed:\n{out[-2000:]}")
    return summary(world_id, read_env(env_path(world_id)), await containers(world_id))
