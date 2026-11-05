"""How much the infrastructure weighs: CPU and memory of every container of the stack, and of the host.

``GET /admin/infra`` (superusers only). Container figures come from the Docker API through a
read-only socket proxy (``OVIAN_DOCKER_URL``, e.g. ``http://dockerproxy:2375``; containers and
info only, no writes), for the containers of the compose project ``OVIAN_COMPOSE_PROJECT``
(``ovian``). Host figures come from ``/proc/stat`` and ``/proc/meminfo`` of the host, mounted
read-only at ``OVIAN_HOST_PROC`` (``/host/proc``). A reading is cached for a few seconds.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter

from ..errors import GameError
from .admin import AdminId
from .base import Module

router = APIRouter(prefix="/admin", tags=["admin"])
CACHE_SECONDS = 4.0
_cache: dict[str, Any] = {"at": 0.0, "data": None}
_last_cpu: dict[str, tuple[int, int]] = {}


def _docker_url() -> str:
    return os.environ.get("OVIAN_DOCKER_URL", "")


def _proc() -> str:
    return os.environ.get("OVIAN_HOST_PROC", "/host/proc")


def _cpu_times() -> tuple[int, int] | None:
    """(busy, total) jiffies of the host, from /proc/stat."""
    try:
        with open(os.path.join(_proc(), "stat")) as f:
            parts = [int(x) for x in f.readline().split()[1:]]
    except OSError:
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts) - idle, sum(parts)


async def host() -> dict[str, Any] | None:
    a = _last_cpu.get("host") or _cpu_times()
    if a is None:
        return None
    if "host" not in _last_cpu:
        await asyncio.sleep(0.5)
    b = _cpu_times()
    if b is None:
        return None
    _last_cpu["host"] = b
    busy, total = b[0] - a[0], b[1] - a[1]
    mem: dict[str, int] = {}
    try:
        with open(os.path.join(_proc(), "meminfo")) as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    cpus = os.cpu_count() or 1
    total_mem = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    return {"cpus": cpus, "cpu_percent": round(100.0 * busy / total, 1) if total > 0 else 0.0,
            "mem_total": total_mem, "mem_used": total_mem - available, "mem_available": available}


def _container(c: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    cpu, pre = s.get("cpu_stats") or {}, s.get("precpu_stats") or {}
    cdelta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (pre.get("cpu_usage") or {}).get("total_usage", 0)
    sdelta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    online = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    m = s.get("memory_stats") or {}
    cache = (m.get("stats") or {}).get("total_inactive_file", (m.get("stats") or {}).get("cache", 0))
    labels = c.get("Labels") or {}
    return {
        "name": (c.get("Names") or ["?"])[0].lstrip("/"),
        "service": labels.get("com.docker.compose.service"),
        "image": c.get("Image"),
        "state": c.get("State"),
        "status": c.get("Status"),
        # percent of one core, like `docker stats` (100% = one core busy)
        "cpu_percent": round(100.0 * cdelta / sdelta * online, 1) if sdelta > 0 and cdelta >= 0 else 0.0,
        "mem_used": max(0, m.get("usage", 0) - cache),
        "mem_limit": m.get("limit", 0),
        "pids": (s.get("pids_stats") or {}).get("current"),
    }


async def containers() -> list[dict[str, Any]]:
    url = _docker_url()
    if not url:
        raise GameError(503, "no_docker", "OVIAN_DOCKER_URL is not set: the server cannot see the containers")
    project = os.environ.get("OVIAN_COMPOSE_PROJECT", "ovian")
    async with httpx.AsyncClient(base_url=url, timeout=10) as http:
        r = await http.get("/containers/json", params={"filters": f'{{"label":["com.docker.compose.project={project}"]}}'})
        r.raise_for_status()
        listed = r.json()

        async def one(c: dict[str, Any]) -> dict[str, Any]:
            s = await http.get(f"/containers/{c['Id']}/stats", params={"stream": "false"})
            return _container(c, s.json() if s.status_code == 200 else {})

        out = await asyncio.gather(*(one(c) for c in listed))
    return sorted(out, key=lambda x: (-x["cpu_percent"], x["name"]))


@router.get("/infra")
async def infra(_: AdminId) -> dict[str, Any]:
    """CPU and memory of the stack's containers and of the host."""
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    try:
        cs = await containers()
    except httpx.HTTPError as e:
        raise GameError(503, "docker_unreachable", f"cannot reach the Docker proxy: {e}") from e
    h = await host()
    data = {
        "at": int(time.time() * 1000),
        "containers": cs,
        "totals": {"cpu_percent": round(sum(c["cpu_percent"] for c in cs), 1), "mem_used": sum(c["mem_used"] for c in cs),
                   "containers": len(cs), "running": sum(1 for c in cs if c["state"] == "running")},
        "host": h,
    }
    _cache.update(at=now, data=data)
    return data


module = Module("infra", router=router)
