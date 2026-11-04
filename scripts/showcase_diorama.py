"""Dev-only: register one player per civ, grow their villages to city phase straight
in the database, and screenshot each in the diorama. Never run against a real world.

    docker run --rm --network ovian_default -v "$PWD/scripts:/s:ro" -v "$PWD/shots:/shots" \
      -e OVIAN_DB=postgresql://ovian:ovian@db:5432/ovian_antiquity \
      mcr.microsoft.com/playwright/python:v1.49.0-noble \
      sh -c "pip -q install playwright==1.49.0 httpx asyncpg && python /s/showcase_diorama.py rome athen han"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import asyncpg
import httpx
from playwright.sync_api import sync_playwright

API = os.environ.get("OVIAN_API", "http://server:8000/api/v1")
WEB = os.environ.get("OVIAN_DIORAMA", "http://diorama")
DB = os.environ["OVIAN_DB"]
SHOTS = os.environ.get("OVIAN_SHOTS", "/shots")

LEVELS = {"civic_centre": 60, "storehouse": 8, "farmstead": 6, "house": 4, "rally_point": 3, "barracks": 10,
          "stable": 5, "fortress": 2, "wall": 6, "temple": 8, "university": 6}
EXTRA = ["house", "house", "barracks", "storehouse"]  # repeatable buildings, a second copy each
FIELD_LEVELS = [1, 3, 6, 9, 0, 2, 5, 8, 1, 4, 7, 10, 0, 2, 4, 6, 8, 10]


async def grow(village_id: int) -> None:
    conn = await asyncpg.connect(DB)
    state = json.loads(await conn.fetchval("SELECT state FROM villages WHERE id = $1", village_id))
    slots = state["slots"]
    fields = len(FIELD_LEVELS)
    for i in range(fields):
        slots[i]["level"] = FIELD_LEVELS[i]
    center = [*LEVELS, *EXTRA]
    for i, b in enumerate(center):
        slots[fields + i] = {"building": b, "level": LEVELS[b]}
    state["techs"] = ["philosophy", "architecture"]
    await conn.execute("UPDATE villages SET state = $1 WHERE id = $2", json.dumps(state), village_id)
    await conn.close()


def main(civs: list[str]) -> int:
    accounts = []
    for civ in civs:
        name = f"{civ}{uuid.uuid4().hex[:4]}"
        r = httpx.post(f"{API}/auth/register", json={"username": name, "password": "password123", "tribe": civ}).json()
        asyncio.run(grow(r["village_id"]))
        accounts.append((civ, r["token"]))
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
        for civ, token in accounts:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(WEB + "/welcome")
            page.evaluate("t => localStorage.setItem('ovian.token', t)", token)
            page.goto(WEB)
            page.wait_for_selector("canvas.scene-canvas", timeout=20000)
            page.wait_for_timeout(14000)
            page.screenshot(path=f"{SHOTS}/city-{civ}.png")
            box = page.locator("canvas.scene-canvas").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            for _ in range(6):
                page.mouse.wheel(0, 400)
                page.wait_for_timeout(250)
            page.wait_for_timeout(5000)
            page.screenshot(path=f"{SHOTS}/city-{civ}-wide.png")
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["rome"]))
