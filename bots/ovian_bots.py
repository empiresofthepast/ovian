"""Ovian AI rulers: friendly NPC kingdoms that play through the public HTTP API.

Each ruler is an ordinary account (marked as a bot by the server through
OVIAN_BOT_USERS). Every TICK_SECONDS it looks at its cities and plays a simple,
rule-based game: answers omens, builds (resource fields, storage, the city
centre, barracks, temple, market, houses), trains cheap infantry, raids the
nearest barbarian camp, picks a government once and enters festivals. It never
attacks human players and never uses admin endpoints.

A very small local LLM (Ollama, default a 1.7B "Bonsai" model) gives the rulers a
voice: now and then one of them posts an in-character proclamation to the global
chat, and they answer players who mention them by name. If the LLM is down,
canned lines are used instead.

Configuration (environment):
  OVIAN_API_URL        http://server:8000
  OVIAN_BOTS           "Name:tribe:persona;..." (persona: statesman, general, warlord, priest, builder, or free text)
  OVIAN_BOT_PASSWORD   shared password of the bot accounts (required)
  OLLAMA_URL           http://host.docker.internal:11434
  OLLAMA_MODEL         hf.co/prism-ml/Bonsai-1.7B-gguf:Q1_0
  TICK_SECONDS         60
  CHAT_EVERY_MINUTES   45 (with +-30% jitter; 0 disables proclamations)
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import re
import time
from typing import Any

import httpx

API = os.environ.get("OVIAN_API_URL", "http://server:8000").rstrip("/") + "/api/v1"
PASSWORD = os.environ.get("OVIAN_BOT_PASSWORD", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hf.co/prism-ml/Bonsai-1.7B-gguf:Q1_0")
TICK = float(os.environ.get("TICK_SECONDS", "60"))
CHAT_EVERY = float(os.environ.get("CHAT_EVERY_MINUTES", "45")) * 60
DEFAULT_BOTS = ("Pericles:athen:statesman;Hannibal:cart:general;Vercingetorix:gaul:warlord;"
                "Ashoka:maur:priest;Cyrus:achae:builder;Boudica:brit:warlord")

PERSONAS = {
    "statesman": ("a wise, eloquent statesman who loves democracy, trade and great buildings", "republic"),
    "general": ("a bold, cunning general who speaks of strategy, discipline and glory", "monarchy"),
    "warlord": ("a proud, fierce tribal chieftain who speaks bluntly of honour and raids", "tyranny"),
    "priest": ("a pious ruler guided by the gods, calm and generous", "theocracy"),
    "builder": ("a patient king of kings who builds roads, granaries and gardens", "oligarchy"),
}
CANNED = [
    "{city} stands strong. Let every traveller find bread and shelter within our walls.",
    "The {season} winds blow over {city}. Our granaries are full and our spears are sharp.",
    "Hear me, neighbours: {city} seeks friendship, not war. The barbarians are our only foes.",
    "Another stone is laid in {city}. Patience builds what haste destroys.",
]
CAPITALS = {"athen": "Athens", "spart": "Sparta", "mace": "Pella", "ptol": "Alexandria", "sele": "Seleucia", "rome": "Roma",
            "cart": "Carthage", "iber": "Numantia", "gaul": "Alesia", "brit": "Camulodunon", "germ": "Aliso", "achae": "Persepolis",
            "maur": "Pataliputra", "kush": "Meroe", "han": "Chang'an"}
REPLIES = ["Well spoken, {who}. {city} remembers its friends.", "{who}, my gates are open to honest neighbours.",
           "Patience, {who}. Great things are built one stone at a time."]

log = logging.getLogger("bots")
llm_lock = asyncio.Lock()


def clean(text: str) -> str:
    """Strip think tags, emojis, hashtags and quotes; keep at most two sentences."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"</?think>", "", text)
    text = re.sub(r"#\w+", "", text)
    text = "".join(ch for ch in text if ord(ch) < 0x2000 or 0x2010 <= ord(ch) <= 0x2027)
    text = " ".join(text.replace("*", "").split()).strip(" \"'")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:2])[:400].strip()


async def ask_llm(http: httpx.AsyncClient, system: str, prompt: str) -> str | None:
    """One short completion from Ollama, or None. Only one call runs at a time."""
    body: dict[str, Any] = {"model": OLLAMA_MODEL, "system": system, "prompt": prompt, "stream": False, "think": False,
                            "options": {"num_predict": 80, "temperature": 0.8}}
    async with llm_lock:
        try:
            r = await http.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=60)
            if r.status_code == 400 and "think" in r.text:  # model without a thinking switch
                body.pop("think")
                r = await http.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=60)
            r.raise_for_status()
            text = clean(r.json().get("response", ""))
        except (httpx.HTTPError, ValueError) as e:
            log.warning("llm unavailable: %s", e)
            return None
    bad = ("as an ai", "language model", "assistant", "i cannot", "i'm sorry")
    if len(text) < 12 or any(b in text.lower() for b in bad):
        return None
    return text


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(f"{status} {code}")
        self.status, self.code = status, code


class World:
    """Static data shared by every bot: the content pack and the world speed."""

    def __init__(self, pack: dict[str, Any], speed: float):
        self.pack, self.speed = pack, speed
        self.buildings = {b["id"]: b for b in pack["buildings"]}
        self.fields: list[str] = pack["village"]["field_slots"]
        # extra fields (opened by the growth building) follow the center sites
        self.extra_base: int = len(self.fields) + int(pack["village"]["center_slots"])
        self.growth: str = pack["village"].get("growth", {}).get("building", "civic_centre")
        self.produces = {b["id"]: b["effects"]["production"]["resource"] for b in pack["buildings"]
                         if "production" in (b.get("effects") or {})}
        self.stores = {b["id"]: b["effects"]["storage"]["resources"] for b in pack["buildings"]
                       if "storage" in (b.get("effects") or {})}

    def cost(self, building: str, level: int) -> dict[str, float]:
        c = self.buildings[building]["cost"]
        return {r: round(n * c["factor"] ** (level - 1)) for r, n in c["base"].items()}


class Bot:
    def __init__(self, name: str, tribe: str, persona: str, http: httpx.AsyncClient, world: World):
        self.name, self.tribe, self.http, self.world = name, tribe, http, world
        self.voice, self.government = PERSONAS.get(persona, (persona, None))
        self.persona = persona
        self.token: str | None = None
        self.cities: list[int] = []
        self.news: list[str] = []  # recent real events, for the LLM
        self.city_name = name
        self.gov_done = False
        self.seen: set[str] = set()
        self.ticks = 0

    # ------------------------------------------------------------- http
    async def call(self, method: str, path: str, body: Any = None, auth: bool = True, **params: Any) -> Any:
        for attempt in (0, 1):
            if auth and not self.token:
                await self.login()
            headers = {"authorization": f"Bearer {self.token}"} if auth else {}
            r = await self.http.request(method, API + path, json=body, params=params or None, headers=headers, timeout=30)
            if r.status_code == 401 and auth and attempt == 0:
                self.token = None
                continue
            if r.status_code >= 400:
                try:
                    code = r.json().get("error") or str(r.json().get("detail"))
                except ValueError:
                    code = r.text[:80]
                raise ApiError(r.status_code, code)
            return r.json() if r.content else None
        raise ApiError(401, "unauthorized")

    async def login(self) -> None:
        creds = {"username": self.name, "password": PASSWORD}
        try:
            data = await self.call("POST", "/auth/login", creds, auth=False)
        except ApiError as e:
            if e.status != 401:
                raise
            data = await self.call("POST", "/auth/register", creds | {"tribe": self.tribe}, auth=False)
            log.info("%s: registered as %s", self.name, self.tribe)
        self.token = data["token"]
        me = await self.call("GET", "/me")
        self.cities = [v["id"] for v in me["villages"]]
        if me["villages"]:
            self.city_name = me["villages"][0]["name"]
        log.info("%s: logged in, %d cities, bot=%s", self.name, len(self.cities), me.get("bot"))

    def note(self, text: str, news: str | None = None) -> None:
        """Log an action; ``news`` is how the ruler would tell it (fed to the LLM)."""
        log.info("%s: %s", self.name, text)
        self.news = (self.news + [news or text])[-6:]

    def label(self, building: str) -> str:
        return self.world.buildings[building].get("name", building.replace("_", " ")).lower()

    # ------------------------------------------------------------- play
    async def tick(self) -> None:
        if not self.token:
            await self.login()
        self.ticks += 1
        if self.ticks % 30 == 1:  # pick up new cities now and then
            me = await self.call("GET", "/me")
            self.cities = [v["id"] for v in me["villages"]]
        for vid in self.cities:
            v = await self.call("GET", f"/villages/{vid}")
            if v["name"].endswith("'s village") and self.tribe in CAPITALS:  # give the first city a proper name
                name = CAPITALS[self.tribe] if vid == self.cities[0] else f"New {CAPITALS[self.tribe]}"
                v = await self.call("PATCH", f"/villages/{vid}", {"name": name})
                self.note(f"named the city {name}")
            self.city_name = v["name"] if vid == self.cities[0] else self.city_name
            await self.omen(v)
            await self.build(v)
            await self.train(v)
            await self.raid(v)
        if not self.gov_done and self.ticks % 10 == 3:
            await self.choose_government()
        if self.ticks % 15 == 5 and self.cities:
            await self.festival(self.cities[0])

    async def omen(self, v: dict[str, Any]) -> None:
        o = v.get("omen")
        if not o:
            return
        res = v["state"]["resources"]
        ok = [c for c in o["choices"] if c.get("available", True) and all(res.get(r, 0) >= n for r, n in c.get("cost", {}).items())]
        if not ok:
            return
        if self.persona in ("warlord", "general"):
            choice = max(ok, key=lambda c: sum(c.get("gain", {}).values()) + 10 * (c.get("boost") or 0))
        elif self.persona in ("statesman", "priest", "builder"):
            choice = max(ok, key=lambda c: (c.get("contentment") or 0) + (c.get("favor") or 0) / 4)
        else:
            choice = random.choice(ok)
        await self.call("POST", f"/villages/{v['id']}/omen/{choice['id']}")
        self.note(f"{o['title']} in {v['name']}: chose to {choice['label'].lower()}")

    def build_options(self, v: dict[str, Any]) -> list[tuple[int, str]]:
        """Candidate (slot, building) orders, best first."""
        w, eco, slots = self.world, v["economy"], v["state"]["slots"]
        res, cap = v["state"]["resources"], eco["capacity"]
        nf = len(w.fields)
        queued = {q["slot"] for q in v["build_queue"]}
        levels: dict[str, int] = {}
        where: dict[str, list[int]] = {}
        for i, s in enumerate(slots):
            if s.get("building"):
                levels[s["building"]] = max(levels.get(s["building"], 0), s["level"])
                where.setdefault(s["building"], []).append(i)
        for q in v["build_queue"]:
            where.setdefault(q["building"], []).append(q["slot"])
        empty = [i for i in range(nf, nf + eco["center_sites"]) if i < len(slots) and not slots[i].get("building") and i not in queued]
        out: list[tuple[int, str]] = []

        def upgrade(b: str, below: int = 99) -> None:
            spots = [i for i in where.get(b, []) if i not in queued and slots[i]["level"] < below]
            if spots:
                out.append((min(spots, key=lambda i: slots[i]["level"]), b))
            elif not where.get(b) and empty:
                out.append((empty[0], b))

        full = [r for r in res if res[r] >= 0.85 * cap.get(r, 1)]
        for b, rs in w.stores.items():
            if any(r in full for r in rs):
                upgrade(b)
        all_fields = [*range(nf), *range(w.extra_base, w.extra_base + int(eco.get("extra_fields", 0)))]
        fields = [i for i in all_fields if i < len(slots) and i not in queued]
        prod = eco.get("production", {})
        lacking = sorted(w.produces.values(), key=lambda r: prod.get(r, 0) / (2 if r == "food" else 1))
        for r in lacking[:2]:
            mine = [i for i in fields if w.produces.get(slots[i]["building"]) == r]
            if mine:
                low = min(mine, key=lambda i: slots[i]["level"])
                out.append((low, slots[low]["building"]))
        min_field = min((slots[i]["level"] for i in range(nf)), default=0)
        centre = levels.get(w.growth, 0)
        if centre <= min_field + 2:
            upgrade(w.growth)
        martial = self.persona in ("general", "warlord")
        upgrade("barracks", below=max(1, centre // (1 if martial else 2)))
        for b in ("temple", "market") if not martial else ("market", "temple"):
            upgrade(b, below=max(1, centre // 3))
        upgrade("house", below=max(1, centre // 2))
        upgrade("wall", below=max(1, centre // 3))
        if fields:
            i = min(fields, key=lambda i: slots[i]["level"])
            out.append((i, slots[i]["building"]))
        return out

    async def build(self, v: dict[str, Any]) -> None:
        eco, w = v["economy"], self.world
        room = eco["build_queue"] - len(v["build_queue"])
        if room <= 0:
            return
        slots, res = v["state"]["slots"], dict(v["state"]["resources"])
        levels: dict[str, int] = {}
        for s in slots:
            if s.get("building"):
                levels[s["building"]] = max(levels.get(s["building"], 0), s["level"])
        tries, seen = 0, set()
        for slot, b in self.build_options(v):
            if room <= 0 or tries >= 3 or slot in seen or b not in w.buildings:
                continue
            seen.add(slot)
            lvl = slots[slot]["level"] + 1
            bonus = sum(int(t.get("field_levels", 0)) for t in w.pack.get("techs", []) if t["id"] in v["state"].get("techs", [])) \
                if w.buildings[b].get("slot") == "field" else 0
            if lvl > w.buildings[b]["max_level"] + bonus:
                continue
            if any(levels.get(rb, 0) < n for rb, n in (w.buildings[b].get("requires") or {}).items()):
                continue
            cost = w.cost(b, lvl)
            if any(res.get(r, 0) < n for r, n in cost.items()):
                continue
            tries += 1
            body = {"slot": slot} | ({"building": b} if not slots[slot].get("building") and slot >= len(w.fields) else {})
            try:
                nv = await self.call("POST", f"/villages/{v['id']}/build", body)
            except ApiError as e:
                if e.status != 409:
                    raise
                log.debug("%s: build %s refused: %s", self.name, b, e.code)
                continue
            res = nv["state"]["resources"]
            room -= 1
            what = f"began building a {self.label(b)}" if lvl == 1 else f"raised the {self.label(b)} to level {lvl}"
            self.note(f"build {b} level {lvl} in {v['name']}", f"{what} in {v['name']}")

    def infantry(self, v: dict[str, Any]) -> dict[str, Any] | None:
        levels: dict[str, int] = {}
        for s in v["state"]["slots"]:
            if s.get("building"):
                levels[s["building"]] = max(levels.get(s["building"], 0), s["level"])
        units = [u for u in self.world.pack["units"] if u["tribe"] == self.tribe and u["class"] == "infantry"
                 and u.get("attack", 0) > 0 and levels.get(u["building"], 0) > 0 and not u.get("techs")
                 and all(levels.get(b, 0) >= n for b, n in (u.get("requires") or {}).items())]
        return min(units, key=lambda u: sum(u["cost"].values()), default=None)

    async def train(self, v: dict[str, Any]) -> None:
        u = self.infantry(v)
        if u is None or v["training"]:
            return
        eco, res = v["economy"], v["state"]["resources"]
        if sum(res.values()) < 0.5 * sum(eco["capacity"].values()):
            return
        food_room = eco["production"].get("food", 0) - 0.25 * eco["gross"].get("food", 0)
        by_food = int(food_room / max(u.get("upkeep", 1) * self.world.speed, 1))
        by_cost = min(int(0.4 * res.get(r, 0) / n) for r, n in u["cost"].items() if n)
        count = min(by_food, by_cost, 50)
        if count < 1:
            return
        try:
            await self.call("POST", f"/villages/{v['id']}/train", {"unit": u["id"], "count": count})
            self.note(f"training {count} {u['id']} in {v['name']}", f"{v['name']} trains {count} new {u['name'].lower()}s")
        except ApiError as e:
            if e.status != 409:
                raise

    async def raid(self, v: dict[str, Any]) -> None:
        out = v["movements"]["outgoing"]
        for m in out:
            if m["kind"] == "return" and sum((m.get("loot") or {}).values()) > 0 and f"loot{m['id']}" not in self.seen:
                self.seen.add(f"loot{m['id']}")
                self.note(f"raid {m['id']} returns with {int(sum(m['loot'].values()))} loot",
                          f"our raiders came home from a barbarian camp with {int(sum(m['loot'].values()))} loads of spoils")
        if out:
            return
        units = v["state"].get("units", {})
        mine = {u["id"]: u for u in self.world.pack["units"] if u["tribe"] == self.tribe}
        army = {k: n for k, n in units.items() if k in mine and mine[k]["class"] in ("infantry", "cavalry")}
        total = sum(army.values())
        if total < (20 if self.persona in ("general", "warlord") else 30):
            return
        m = await self.call("GET", "/map", auth=False, x=v["x"] - 32, y=v["y"] - 32, w=64, h=64)
        camps = [c for c in m["villages"] if c.get("npc") and c.get("camp_level") is not None
                 and int(c["camp_level"]) * 12 * 2.5 <= total]
        if not camps:
            return
        c = min(camps, key=lambda c: math.hypot(c["x"] - v["x"], c["y"] - v["y"]))
        send = {k: math.ceil(n * 0.8) for k, n in army.items()}
        try:
            await self.call("POST", f"/villages/{v['id']}/send", {"kind": "raid", "x": c["x"], "y": c["y"], "units": send})
            self.note(f"raid {c['name']} at ({c['x']}|{c['y']}) with {sum(send.values())}",
                      f"{sum(send.values())} warriors of {v['name']} marched out against a barbarian camp")
        except ApiError as e:
            if e.status not in (404, 409):
                raise

    async def choose_government(self) -> None:
        g = await self.call("GET", "/me/government")
        self.gov_done = True
        want = self.government
        if not want or g["current"] == want or g.get("anarchy_until") or want not in {o["id"] for o in g["options"]}:
            return
        try:
            await self.call("POST", "/me/government", {"id": want})
            self.note(f"government -> {want}", f"we proclaimed a new constitution: {want}")
        except ApiError as e:
            if e.status != 409:
                raise

    async def festival(self, vid: int) -> None:
        cal = await self.call("GET", "/calendar")
        f = cal.get("festival") or {}
        if not f.get("active"):
            return
        v = await self.call("GET", f"/villages/{vid}")
        res = v["state"]["resources"]
        for cid, c in f.get("contests", {}).items():
            key = f"{f['number']}:{cid}"
            if key in self.seen or c.get("mine") is not None:
                continue
            self.seen.add(key)
            body: dict[str, Any] = {"village_id": vid}
            if c.get("kind", "resources") == "resources":
                body["resources"] = {r: int(res.get(r, 0) * 0.1) for r in c.get("resources") or res}
            try:
                await self.call("POST", f"/festival/{cid}", body)
                self.note(f"entered the {c.get('name', cid)} at the {f.get('name', 'festival')}")
            except ApiError as e:
                if e.status != 409:
                    raise

    # ------------------------------------------------------------- voice
    def system(self) -> str:
        return (f"You are {self.name}, ruler of the city of {self.city_name}, {self.voice}. "
                "You rule in character in an ancient world. Answer with one or two short sentences, in plain English. "
                "No emojis, no hashtags, no lists. Never say you are an AI, a model or an assistant.")

    async def proclaim(self, season: str) -> None:
        facts = "; ".join(self.news[-3:]) or f"{self.city_name} grows quietly"
        prompt = (f"It is {season}. Recent news from your realm: {facts}. Speaking as yourself, in the first person, "
                  "write a short proclamation to the other rulers of the world about one of these events.")
        text = await ask_llm(self.http, self.system(), prompt) or random.choice(CANNED).format(city=self.city_name, season=season)
        await self.call("POST", "/chat/global", {"text": text[:500]})
        log.info("%s says: %s", self.name, text)

    async def reply(self, who: str, said: str) -> None:
        prompt = f'{who}, a ruler of a neighbouring city, says to you: "{said[:300]}". Reply to {who} in one or two sentences.'
        text = await ask_llm(self.http, self.system(), prompt) or random.choice(REPLIES).format(who=who, city=self.city_name)
        await self.call("POST", "/chat/global", {"text": text[:500]})
        log.info("%s replies to %s: %s", self.name, who, text)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not PASSWORD:
        raise SystemExit("OVIAN_BOT_PASSWORD is required")
    specs = [s.split(":", 2) for s in (os.environ.get("OVIAN_BOTS") or DEFAULT_BOTS).split(";") if s.strip()]
    async with httpx.AsyncClient() as http:
        while True:  # wait for the server
            try:
                pack = (await http.get(f"{API}/content", timeout=30)).raise_for_status().json()
                speed = float((await http.get(f"{API}/world", timeout=30)).json().get("speed", 1))
                break
            except (httpx.HTTPError, ValueError) as e:
                log.warning("server not ready: %s", e)
                await asyncio.sleep(10)
        world = World(pack, speed)
        tribes = {t["id"] for t in pack["tribes"]}
        bots = []
        for name, tribe, *rest in specs:
            if tribe not in tribes:
                log.error("%s: unknown tribe %r (pack has %s)", name, tribe, ", ".join(sorted(tribes)))
                continue
            bots.append(Bot(name.strip(), tribe.strip(), (rest[0] if rest else "statesman").strip(), http, world))
        log.info("%d rulers: %s; model %s", len(bots), ", ".join(f"{b.name} ({b.tribe})" for b in bots), OLLAMA_MODEL)
        names = {b.name.lower(): b for b in bots}
        last_seen = max((m["id"] for m in (await http.get(f"{API}/chat/global", params={"limit": 50})).json()), default=0)
        next_chat = time.monotonic() + random.uniform(0.05, 0.3) * CHAT_EVERY
        while True:
            started = time.monotonic()
            for b in bots:
                try:
                    await b.tick()
                except Exception as e:  # noqa: BLE001 - one bot's trouble must not stop the others
                    log.warning("%s: tick failed: %r", b.name, e)
                await asyncio.sleep(0.5)
            try:  # answer players who mention a ruler by name
                msgs = (await http.get(f"{API}/chat/global", params={"limit": 30}, timeout=30)).json()
                for m in msgs:
                    if m["id"] <= last_seen:
                        continue
                    last_seen = m["id"]
                    if m["from"]["name"].lower() in names:
                        continue
                    for key, b in names.items():
                        if re.search(rf"\b{re.escape(key)}\b", m["text"].lower()):
                            await b.reply(m["from"]["name"], m["text"])
                            break
                if CHAT_EVERY > 0 and time.monotonic() >= next_chat and bots:
                    next_chat = time.monotonic() + CHAT_EVERY * random.uniform(0.7, 1.3)
                    b = random.choice([b for b in bots if b.token] or bots)
                    cal = await b.call("GET", "/calendar")
                    await b.proclaim(((cal.get("season") or {}).get("name") or "a new season").lower())
            except Exception as e:  # noqa: BLE001
                log.warning("chat failed: %r", e)
            await asyncio.sleep(max(1.0, TICK - (time.monotonic() - started)))


if __name__ == "__main__":
    asyncio.run(main())
