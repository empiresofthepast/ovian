"""Ovian MCP server: lets an AI assistant (Claude, or any MCP client) run your own cities.

It is a thin layer over the public HTTP API. Each request carries the player's personal
access token (``Authorization: Bearer ovp_…``, created in Settings → AI assistants), which is
passed on to the API unchanged, so the assistant can do exactly what the player can do
from the game, no more. Streamable HTTP, stateless, at ``/mcp``.

    OVIAN_API_URL       http://server:8000   the game server
    OVIAN_MCP_HOSTS     comma-separated Host headers to accept (default: any)
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API = os.environ.get("OVIAN_API_URL", "http://server:8000").rstrip("/") + "/api/v1"
HOSTS = [h.strip() for h in os.environ.get("OVIAN_MCP_HOSTS", "").split(",") if h.strip()]

mcp = FastMCP(
    "ovian",
    instructions=(
        "You manage the player's cities in Ovian, a browser strategy game of antiquity. Start with my_empire, "
        "then city_options for a city to see what can be built, trained or researched, with costs and times. "
        "Field sites (index 0-17) produce resources; centre sites hold buildings. Every order is checked by the "
        "game server, which answers with an error code when it is refused. Times are game time at the world's speed. "
        "Ask the player before attacking other players."
    ),
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=bool(HOSTS), allowed_hosts=HOSTS),
)

_pack: dict[str, Any] | None = None


class GameRefused(Exception):
    pass


def _token(ctx: Context) -> str:
    req = getattr(ctx.request_context, "request", None)
    auth = req.headers.get("authorization", "") if req is not None else ""
    if not auth.lower().startswith("bearer "):
        raise GameRefused("No access token. Create one in the game under Settings → AI assistants and send it as "
                          "'Authorization: Bearer ovp_…'.")
    return auth.split(" ", 1)[1].strip()


async def call(ctx: Context, method: str, path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(base_url=API, timeout=30) as c:
        r = await c.request(method, path, json=body, params=params, headers={"Authorization": f"Bearer {_token(ctx)}"})
    if r.status_code == 204:
        return None
    data = r.json() if r.content else None
    if r.status_code >= 400:
        if isinstance(data, dict) and "error" in data:
            raise GameRefused(f"{data['error']}" + (f": {data['message']}" if data.get("message") else ""))
        raise GameRefused(f"HTTP {r.status_code}: {str(data)[:300]}")
    return data


async def pack(ctx: Context) -> dict[str, Any]:
    global _pack
    if _pack is None:
        async with httpx.AsyncClient(base_url=API, timeout=30) as c:
            _pack = (await c.get("/content")).json()
    return _pack


def _when(ms: int | None, now: int) -> str | None:
    if not ms:
        return None
    s = max(0, (ms - now) / 1000)
    left = f"{s:.0f}s" if s < 90 else f"{s / 60:.0f}m" if s < 5400 else f"{s / 3600:.1f}h"
    return f"in {left} ({time.strftime('%H:%M:%S', time.gmtime(ms / 1000))} UTC)"


def _round(m: dict[str, float] | None) -> dict[str, int]:
    return {k: round(v) for k, v in (m or {}).items()}


def _site_open(i: int, x: dict[str, Any], p: dict[str, Any], eco: dict[str, Any]) -> bool:
    """Fields, open center sites, built sites and the extra fields opened so far (they follow the center sites)."""
    vil = p.get("village", {})
    fields, center = len(vil.get("field_slots", [])), int(vil.get("center_slots", 0))
    if x.get("foreign"):  # the foreign quarter an overlord opened: embassy and exchanges
        return True
    if i >= fields + center:
        return i - fields - center < int(eco.get("extra_fields", 0))
    return i < fields or bool(x.get("building") and x.get("level")) or i - fields < int(eco.get("center_sites", 0))


async def summary(ctx: Context, v: dict[str, Any]) -> dict[str, Any]:
    """The village view, cut down to what a ruler needs."""
    p = await pack(ctx)
    names = {b["id"]: b["name"] for b in p.get("buildings", [])}
    units = {u["id"]: u["name"] for u in p.get("units", [])}
    now = v.get("server_time") or int(time.time() * 1000)
    s, eco = v["state"], v.get("economy", {})
    out: dict[str, Any] = {
        "id": v["id"], "name": v["name"], "at": [v["x"], v["y"]], "population": v.get("population"),
        "resources": _round(s.get("resources")), "per_hour": _round(eco.get("production")), "capacity": _round(eco.get("capacity")),
        "phase": eco.get("phase"),
        "sites": [{"site": i, "building": names.get(x["building"], x["building"]), "id": x["building"], "level": x["level"]}
                  | ({"foreign": True} if x.get("foreign") else {})
                  if x.get("building") else {"site": i, "free": True} | ({"foreign": True} if x.get("foreign") else {})
                  for i, x in enumerate(s.get("slots", []))
                  if _site_open(i, x, p, eco)],
        "sites_unlocked_later": sum(1 for i, x in enumerate(s.get("slots", [])) if not _site_open(i, x, p, eco)),
        "troops_home": {units.get(k, k): n for k, n in (s.get("units") or {}).items() if n},
        "starvation": v.get("starvation"),  # troops die, cheapest first, while the food stock is empty and short
        "techs": s.get("techs", []),
        "building": [{"job": j.get("id"), "site": j.get("slot"), "building": names.get(j.get("building"), j.get("building")),
                      "to_level": j.get("level"), "done": _when(j.get("due_at"), now)} for j in v.get("build_queue", [])],
        "training": [{"job": j.get("id"), "unit": units.get(j.get("unit"), j.get("unit")), "left": j.get("remaining"),
                      "done": _when(j.get("finishes_at"), now)} for j in v.get("training", [])],
        "research": [{"job": j.get("id"), "tech": j.get("tech"), "done": _when(j.get("due_at"), now)} for j in v.get("research", [])],
        "incoming": [{"kind": m.get("kind"), "from": (m.get("from") or {}).get("name"), "arrives": _when(m.get("arrives_at"), now)}
                     for m in (v.get("movements") or {}).get("incoming", [])],
        "outgoing": [{"kind": m.get("kind"), "to": (m.get("to") or {}).get("name"), "arrives": _when(m.get("arrives_at"), now)}
                     for m in (v.get("movements") or {}).get("outgoing", [])],
    }
    if v.get("contentment"):
        out["contentment"] = v["contentment"].get("score")
    if v.get("season"):
        out["season"] = v["season"].get("name")
    if v.get("government"):
        out["government"] = v["government"].get("label")
    if v.get("omen"):
        o = v["omen"]
        out["omen"] = {"title": o.get("title"), "text": o.get("text"), "default": o.get("default"), "decide": _when(o.get("expires_at"), now),
                       "choices": [{"id": c["id"], "label": c["label"], "cost": _round(c.get("cost")), "available": c.get("available")}
                                   for c in o.get("choices", [])]}
    if v.get("submission"):
        out["tribute_to"] = v["submission"]["village"]["name"]
    if v.get("vassals"):
        out["vassals"] = [x["village"]["name"] for x in v["vassals"]]
        levies = {x["village"]["name"]: {"city_id": x["village"]["id"], "garrison_room": x["garrison"]["capacity"],
                                         "levied": x["garrison"]["auxiliaries"]["levied"], "in_training": x["garrison"]["auxiliaries"]["queued"],
                                         "can_levy": {o["unit"]: _round(o["cost_each"]) for o in x["garrison"]["auxiliaries"]["options"]}}
                  for x in v["vassals"] if (x.get("garrison") or {}).get("auxiliaries")}
        if levies:
            out["auxiliaries"] = levies
    if v.get("governor"):
        g = v["governor"]
        out["governor"] = {"name": g["name"], "prefect": g.get("prefect"), "traits": [t.get("name", t["id"]) for t in g.get("traits", [])]}
    a = v.get("archaeology")
    if a:
        out["archaeology"] = {
            "dig_cost": _round(a.get("cost")),
            "layers": {k: [f"{names.get(x['building'], x['building'])} ({x['end']}{', dug' if x['dug'] else ''})" for x in site["layers"]]
                       for k, site in a.get("sites", {}).items() if site["layers"]},
            "dug_to_rock": [int(k) for k, site in a.get("sites", {}).items() if site.get("probed")],
            "digging": [{"site": d["slot"], "done": _when(d["due_at"], now)} for d in a.get("digs", [])],
            "finds_here": [{"id": f["id"], "name": f["name"], "grade": f["grade"], "culture": f["culture"],
                            "shown": f["id"] in a["display"]["shown"]} for f in a.get("finds", [])],
            "temple_room": a["display"]["room"]}
    return out


# ---------------------------------------------------------------------------- reading


@mcp.tool()
async def my_empire(ctx: Context) -> dict[str, Any]:
    """Who you are and all your cities, each with resources, production, queues and armies on the move."""
    me = await call(ctx, "GET", "/me")
    cities = [await summary(ctx, await call(ctx, "GET", f"/villages/{c['id']}")) for c in me["villages"]]
    for c in cities:
        c.pop("sites", None)
    return {"player": me["username"], "tribe": me["tribe"], "unread_reports": me.get("unread_reports"),
            "beginner_protection": me.get("protected_until", 0) > time.time() * 1000, "cities": cities}


@mcp.tool()
async def city(ctx: Context, city_id: int) -> dict[str, Any]:
    """One of your cities in full: every site with its building and level, troops, queues, omen, mood."""
    return await summary(ctx, await call(ctx, "GET", f"/villages/{city_id}"))


@mcp.tool()
async def city_options(ctx: Context, city_id: int, only_available: bool = True) -> dict[str, Any]:
    """What the city can do next: upgrades per site, new buildings for its free sites, units and techs,
    with cost, time in seconds and whether it is affordable now. Blocked items carry the reason."""
    o = await call(ctx, "GET", f"/villages/{city_id}/options")
    if only_available:
        for k in ("upgrades", "new_buildings", "units", "techs"):
            o[k] = [x for x in o[k] if not x.get("blocked")]
    for k in ("upgrades", "new_buildings", "units", "techs"):
        for x in o[k]:
            for f in ("cost", "cost_each"):
                if f in x:
                    x[f] = _round(x[f])
    o["resources"] = _round(o["resources"])
    return o


@mcp.tool()
async def world_map(ctx: Context, x: int, y: int, radius: int = 7) -> list[dict[str, Any]]:
    """Cities and barbarian camps around (x, y), nearest first, with owner, population and distance."""
    radius = max(1, min(radius, 31))
    m = await call(ctx, "GET", "/map", params={"x": x - radius, "y": y - radius, "w": 2 * radius + 1, "h": 2 * radius + 1})
    out = [{"id": c["id"], "name": c["name"], "at": [c["x"], c["y"]], "player": c.get("player_name"), "tribe": c.get("tribe"),
            "population": c.get("population"), "distance": round(((c["x"] - x) ** 2 + (c["y"] - y) ** 2) ** 0.5, 1),
            **({"vassal_of": c["overlord_name"]} if c.get("overlord_name") else {}),
            **({"protected": True} if c.get("protected") else {})} for c in m.get("villages", [])]
    return sorted(out, key=lambda c: c["distance"])


@mcp.tool()
async def reports(ctx: Context, limit: int = 15) -> list[dict[str, Any]]:
    """Your latest reports (battles, scouting, trade, events), newest first."""
    r = await call(ctx, "GET", "/reports", params={"limit": limit})
    items = r.get("reports", r) if isinstance(r, dict) else r
    return [{k: x.get(k) for k in ("id", "kind", "title", "created_at", "read")} for x in items[:limit]]


@mcp.tool()
async def read_report(ctx: Context, report_id: int) -> dict[str, Any]:
    """One report in full."""
    return await call(ctx, "GET", f"/reports/{report_id}")


@mcp.tool()
async def quests(ctx: Context) -> dict[str, Any]:
    """Open quests with progress and rewards."""
    return await call(ctx, "GET", "/quests")


# ---------------------------------------------------------------------------- orders


async def _order(ctx: Context, method: str, path: str, body: Any, city_id: int) -> dict[str, Any]:
    v = await call(ctx, method, path, body)
    if isinstance(v, dict) and "state" in v:
        return {"ok": True, "city": await summary(ctx, v)}
    return {"ok": True, "result": v if v is not None else await summary(ctx, await call(ctx, "GET", f"/villages/{city_id}"))}


@mcp.tool()
async def build(ctx: Context, city_id: int, site: int, building: str | None = None) -> dict[str, Any]:
    """Upgrade the building on a site by one level, or raise a new one on a free centre site
    (then give its id, e.g. 'barracks'; see city_options)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/build", {"slot": site, "building": building}, city_id)


@mcp.tool()
async def train(ctx: Context, city_id: int, unit: str, count: int) -> dict[str, Any]:
    """Train units (unit id from city_options)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/train", {"unit": unit, "count": count}, city_id)


@mcp.tool()
async def research(ctx: Context, city_id: int, tech: str) -> dict[str, Any]:
    """Research a technology (tech id from city_options)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/research", {"tech": tech}, city_id)


@mcp.tool()
async def cancel_job(ctx: Context, city_id: int, job_id: int) -> dict[str, Any]:
    """Cancel a construction, training or research job; what was not used is refunded."""
    return await _order(ctx, "DELETE", f"/villages/{city_id}/jobs/{job_id}", None, city_id)


@mcp.tool()
async def demolish(ctx: Context, city_id: int, site: int) -> dict[str, Any]:
    """Pull down the building on a center site at once: the site is free again and half of what all its levels
    cost comes back (what does not fit in storage is lost). Fields, the city centre, great buildings and the
    wonder cannot be pulled down. This cannot be undone: ask the player first."""
    return await _order(ctx, "POST", f"/villages/{city_id}/sites/{site}/demolish", None, city_id)


@mcp.tool()
async def build_embassy(ctx: Context, vassal_city_id: int, paying_city_id: int) -> dict[str, Any]:
    """Raise your embassy in one of your vassal cities by one level, paid by one of your own cities. Only the
    overlord can build it; it calms the vassal. It is left in ruins if the vassal breaks free."""
    return await _order(ctx, "POST", f"/villages/{vassal_city_id}/embassy", {"from": paying_city_id}, paying_city_id)


@mcp.tool()
async def build_overlord_site(ctx: Context, vassal_city_id: int, site: int, paying_city_id: int,
                              building: Literal["cultural_exchange", "garrison"] | None = None) -> dict[str, Any]:
    """Raise a building on one of your overlord sites in a vassal city by one level, paid by one of your cities.
    cultural_exchange: part of the vassal's culture goes to your city. garrison: your troops stationed there may set
    out from it. Give the building only for an empty site (see the vassal's sites in city)."""
    return await _order(ctx, "POST", f"/villages/{vassal_city_id}/foreign/{site}", {"from": paying_city_id, "building": building}, paying_city_id)


@mcp.tool()
async def excavate(ctx: Context, city_id: int, site: int) -> dict[str, Any]:
    """Dig an empty town site or a ruin. What stood there before (a pulled-down building, a lost overlord's embassy) or,
    below everything, the remains of a prehistoric people come up as a find; finds shown in the city's temples add culture.
    A site dug down to the rock cannot be dug again. Costs resources and takes a while (see archaeology in city)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/sites/{site}/excavate", None, city_id)


@mcp.tool()
async def levy_auxiliaries(ctx: Context, vassal_city_id: int, paying_city_id: int, unit: str, count: int) -> dict[str, Any]:
    """Train the vassal's own troops in your garrison in that city, paid by one of your cities (dearer than at home).
    They count against the garrison's room and anger the city; if it breaks free they join it. See auxiliaries in city."""
    return await _order(ctx, "POST", f"/villages/{vassal_city_id}/auxiliaries",
                        {"from": paying_city_id, "unit": unit, "count": count}, paying_city_id)


@mcp.tool()
async def governors(ctx: Context) -> dict[str, Any]:
    """Your governors (where they rule or travel), the candidates you could hire with their traits, and the price."""
    return await call(ctx, "GET", "/me/governors")


@mcp.tool()
async def hire_governor(ctx: Context, candidate: int, paying_city_id: int) -> dict[str, Any]:
    """Hire the candidate with this index (see governors). One governor per city you hold or rule."""
    return await call(ctx, "POST", "/me/governors", {"candidate": candidate, "from": paying_city_id})


@mcp.tool()
async def appoint_governor(ctx: Context, governor_id: int, city_id: int) -> dict[str, Any]:
    """Send a governor to rule one of your cities or a vassal's (there they are a prefect and send the city's own
    governor away; the people resent it). They travel first. Their traits change contentment, unrest, production, defense."""
    return await call(ctx, "POST", f"/governors/{governor_id}/appoint", {"village_id": city_id})


@mcp.tool()
async def recall_governor(ctx: Context, governor_id: int) -> dict[str, Any]:
    """Call a governor back to court; the city is left without one."""
    return await call(ctx, "POST", f"/governors/{governor_id}/recall")


@mcp.tool()
async def send_troops(ctx: Context, city_id: int, kind: Literal["attack", "raid", "reinforce", "scout"], x: int, y: int,
                      units: dict[str, int], hero: bool = False,
                      mission: Literal["look", "sabotage", "steal", "incite"] | None = None,
                      from_garrison: int | None = None) -> dict[str, Any]:
    """Send troops from a city to (x, y). raid = plunder and return; attack = full battle; reinforce = station
    them there; scout = scouts only, with an optional mission. from_garrison = the id of a vassal city where you have a
    garrison: your troops stationed there set out from it instead (and return to it). Ask the player before attacking another player."""
    body: dict[str, Any] = {"kind": kind, "x": x, "y": y, "units": units, "hero": hero}
    if mission:
        body["mission"] = mission
    if from_garrison:
        body["garrison"] = from_garrison
    return await _order(ctx, "POST", f"/villages/{city_id}/send", body, city_id)


@mcp.tool()
async def send_resources(ctx: Context, city_id: int, x: int, y: int, resources: dict[str, float]) -> dict[str, Any]:
    """Send resources with the market's merchants to the city at (x, y)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/market/send", {"x": x, "y": y, "resources": resources}, city_id)


@mcp.tool()
async def answer_omen(ctx: Context, city_id: int, choice: str) -> dict[str, Any]:
    """Answer the omen waiting in a city (choice id from city)."""
    return await _order(ctx, "POST", f"/villages/{city_id}/omen/{choice}", None, city_id)


@mcp.tool()
async def claim_quest(ctx: Context, quest_id: str, city_id: int) -> dict[str, Any]:
    """Collect a finished quest's reward into a city."""
    v = await call(ctx, "POST", f"/quests/{quest_id}/claim", params={"village_id": city_id})
    return {"ok": True, "city": await summary(ctx, v)}


@mcp.tool()
async def rename_city(ctx: Context, city_id: int, name: str) -> dict[str, Any]:
    """Give a city a new name."""
    return await _order(ctx, "PATCH", f"/villages/{city_id}", {"name": name}, city_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
