"""Convert 0 A.D. simulation data into the Ovian "antiquity" content pack.

    python convert.py --zeroad /src/repo --config antiquity.yaml --out ../../content/antiquity

Unit stats come from the resolved 0 A.D. entity templates. Ovian battles add up
attack points against defense points, so each unit's 0 A.D. damage output and
durability are folded into single numbers:

    power = sqrt(effective damage per second x effective hit points)

The geometric mean keeps a unit that hits twice as hard and one that lasts twice
as long equally valuable, as in a Lanchester fight. Damage is taken against the
average armour of the opposing class (bonus multipliers such as spears against
cavalry included), durability against the average damage mix of the attacking
class. Everything is then scaled so the median basic infantryman attacks at
`scale.power`. See docs/antiquity.md.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, field

import yaml

from zeroad import Entity, ZeroAD

EXCLUDE = re.compile(r"(hero_|support_|siege_|ship_|healer|_upgrade|conscript|_slave|_house$|fanatic|_dock$)")
DAMAGE = ("Hack", "Pierce", "Crush")


@dataclass
class Candidate:
    civ: str
    template: str
    e: Entity
    kind: str  # infantry | cavalry | champion
    mounted: bool
    attack: dict = field(default_factory=dict)


def r5(x: float) -> int:
    return int(5 * round(x / 5))


def attack_of(e: Entity) -> tuple[str, dict[str, float], float, float] | None:
    for kind in ("Melee", "Ranged"):
        if e.has(f"Attack/{kind}"):
            dmg = e.damage(f"Attack/{kind}/Damage")
            rep = e.num(f"Attack/{kind}/RepeatTime", 1000) / 1000
            rng = e.num(f"Attack/{kind}/MaxRange", 2)
            if dmg:
                return kind, dmg, rep, rng
    return None


def resist(e: Entity) -> dict[str, float]:
    r = e.damage("Resistance/Entity/Damage")
    return {t: r.get(t, 0.0) for t in DAMAGE}


def mean_vec(vs: list[dict[str, float]]) -> dict[str, float]:
    return {t: statistics.fmean(v.get(t, 0.0) for v in vs) if vs else 0.0 for t in DAMAGE}


def norm(v: dict[str, float]) -> dict[str, float]:
    s = sum(v.values()) or 1
    return {t: v.get(t, 0) / s for t in DAMAGE}


def roster(z: ZeroAD, civ: str, cfg: dict) -> list[Candidate]:
    """Every soldier any structure of the civ trains, classified by 0 A.D. class."""
    seen: dict[str, Candidate] = {}
    for path in sorted(glob.glob(os.path.join(z.sim, "templates", "structures", civ, "*.xml"))):
        t = f"structures/{civ}/{os.path.basename(path)[:-4]}"
        try:
            trains = z.entity(t).tokens("Trainer/Entities")
        except (OSError, ValueError):
            continue
        for u in trains:
            u = u.replace("{civ}", civ)
            base = u.split("/")[-1]
            if EXCLUDE.search(base) or re.search(r"_[ae]$", base) or not z.has_template(u) or u in seen:
                continue
            e = z.entity(u)
            cls = e.classes
            mounted = bool(cls & {"Cavalry", "Elephant", "Chariot"})
            if "Champion" in cls and "CitizenSoldier" not in cls:
                kind = "champion"
            elif cls & {"Infantry", "Cavalry", "Elephant"} and "Soldier" in cls:
                kind = "cavalry" if mounted else "infantry"
            else:
                continue
            if attack_of(e) is None:
                continue
            seen[u] = Candidate(civ, u, e, kind, mounted)
    unique: dict[tuple, Candidate] = {}
    for c in seen.values():  # the same soldier offered by several buildings under other names
        unique.setdefault((c.e.text("Identity/GenericName"), c.e.text("VisualActor/Actor")), c)
    return list(unique.values())


def role(c: Candidate, roles: dict) -> tuple[float, float]:
    """(attack, defense) multipliers from the unit's 0 A.D. classes."""
    att = dfn = 1.0
    cls = c.e.classes | ({"Ranged"} if attack_of(c.e)[0] == "Ranged" else set())
    for name, m in roles.items():
        if name in cls:
            att *= m.get("attack", 1)
            dfn *= m.get("defense", 1)
    return att, dfn


def total_cost(e: Entity) -> float:
    return sum(e.costs().values())


def convert(z: ZeroAD, cfg: dict) -> dict:
    sc = cfg["scale"]
    civs = cfg["civs"]
    pools = {c: roster(z, c, cfg) for c in civs}
    everyone = [c for p in pools.values() for c in p]

    inf = [c for c in everyone if not c.mounted]
    cav = [c for c in everyone if c.mounted]
    inf_armour, cav_armour = mean_vec([resist(c.e) for c in inf]), mean_vec([resist(c.e) for c in cav])
    inf_mix = norm(mean_vec([norm(attack_of(c.e)[1]) for c in inf]))
    cav_mix = norm(mean_vec([norm(attack_of(c.e)[1]) for c in cav]))

    def dps(c: Candidate, armour: dict, target: set[str]) -> float:
        kind, dmg, rep, rng = attack_of(c.e)
        eff = sum(dmg.get(t, 0) * 0.9 ** armour[t] for t in DAMAGE)
        mult = 1.0
        for need, m in c.e.bonuses(kind):
            if need and need <= target:
                mult *= m
        bonus = 1 + sc["range_bonus"] * min(rng, 80) if kind == "Ranged" else 1
        return eff * mult * bonus / max(rep, 0.1)

    def ehp(c: Candidate, mix: dict) -> float:
        r = resist(c.e)
        taken = sum(mix[t] * 0.9 ** r[t] for t in DAMAGE) or 1
        return c.e.num("Health/Max", 100) / taken

    share_cav = len(cav) / max(1, len(everyone))
    raw = {}
    for c in everyone:
        vs_inf = dps(c, inf_armour, {"Infantry", "Human"})
        vs_cav = dps(c, cav_armour, {"Cavalry"})
        a = math.sqrt(((1 - share_cav) * vs_inf + share_cav * vs_cav) * ehp(c, norm({t: (1 - share_cav) * inf_mix[t] + share_cav * cav_mix[t] for t in DAMAGE})))
        di = math.sqrt(vs_inf * ehp(c, inf_mix))
        dc = math.sqrt(vs_cav * ehp(c, cav_mix))
        raw[c.template] = (a, di, dc)
    k = sc["power"] / statistics.median(raw[c.template][0] for c in everyone if c.kind == "infantry")

    tribes, units, ext_tribes = [], [], {}
    lim = cfg["roster"]
    tiers = lim["tiers"]
    for civ in civs:
        p = z.entity(f"special/players/{civ}")
        name = p.text("Identity/GenericName", civ)
        history = p.text("Identity/History")
        tribes.append({"id": civ, "name": name, "description": first_sentences(history, 220)})
        pool = pools[civ]
        chosen: list[tuple[Candidate, str]] = []
        for kind, building, n in (("infantry", "barracks", lim["infantry"]), ("cavalry", "stable", lim["cavalry"]), ("champion", "fortress", lim["champions"])):
            group = sorted((c for c in pool if c.kind == kind), key=lambda c: -raw[c.template][0])[:n]
            group.sort(key=lambda c: total_cost(c.e))
            chosen.extend((c, building) for c in group)
        ext_units = {}
        per_building: dict[str, int] = {}
        for c, building in chosen:
            e = c.e
            i = per_building.get(building, 0)
            per_building[building] = i + 1
            tier = tiers[building][min(i, len(tiers[building]) - 1)]
            a, di, dc = raw[c.template]
            ra, rd = role(c, sc.get("roles", {}))
            a, di, dc = a * ra, di * rd, dc * rd
            base = c.template.split("/")[-1].removesuffix("_b")
            uid = f"{civ}_{base}"
            cls = e.classes
            caps = e.node.find("ResourceGatherer/Capacities")
            gather = [float(x.text) for x in caps] if caps is not None else []
            mounted_kind = "cavalry" if c.mounted else "infantry"
            carry = sc["carry"] * max(gather) if gather else sc["carry_default"][mounted_kind]
            up = sc["upkeep"]
            upkeep = up["base"] + (up["cavalry"] if c.mounted else 0) + (up["champion"] if c.kind == "champion" else 0)
            if "Elephant" in cls:
                upkeep += up["elephant"]
            specific = e.text("Identity/SpecificName")
            tooltip = e.text("Identity/Tooltip")
            unit = {
                "id": uid,
                "name": e.text("Identity/GenericName", base),
                "description": " ".join(x for x in [specific + "." if specific else "", tooltip] if x).strip(),
                "tribe": civ,
                "building": building,
                "class": mounted_kind,
                "cost": {r: r5(v * sc["cost"]) for r, v in sorted(e.costs().items(), key=lambda kv: ["food", "wood", "stone", "metal"].index(kv[0])) if r in ("food", "wood", "stone", "metal")},
                "upkeep": upkeep,
                "time": int(10 * round(e.num("Cost/BuildTime", 10) * sc["time"] / 10)),
                "attack": round(a * k),
                "defense": {"infantry": round(di * k), "cavalry": round(dc * k)},
                "speed": max(3, round(e.num("UnitMotion/WalkSpeed", 9) * sc["speed"])),
                "carry": int(carry),
            }
            if tier:
                unit["requires"] = {building: tier}
            tl = lim.get("techs", {}).get(building)
            if isinstance(tl, dict):
                needs = tl.get("mounted" if c.mounted else "foot", [])
            elif tl:
                needs = tl[min(i, len(tl) - 1)]
            else:
                needs = []
            if needs:
                unit["techs"] = list(needs)
            units.append(unit)
            ext_units[uid] = {
                "template": c.template,
                "actor": e.text("VisualActor/Actor"),
                "icon": e.text("Identity/Icon"),
                "specific_name": specific,
            }
        for x in lim.get("extra", []):
            uid = f"{civ}_{x['id']}"
            units.append({"id": uid, "tribe": civ, **{k: v for k, v in x.items() if k not in ("id", "zeroad")}})
            t = f"units/{civ}/{x['zeroad']}" if x.get("zeroad") else None
            if t and z.has_template(t):
                e = z.entity(t)
                ext_units[uid] = {"template": t, "actor": e.text("VisualActor/Actor"), "icon": e.text("Identity/Icon"),
                                  "specific_name": e.text("Identity/SpecificName")}
        ext_buildings = {}
        for b in cfg["buildings"]:
            zt = b.get("zeroad")
            if not zt:
                continue
            found = [f"structures/{civ}/{x}" for x in (zt if isinstance(zt, list) else [zt]) if z.has_template(f"structures/{civ}/{x}")]
            if not found:
                continue
            t = found[0]
            e = z.entity(t)
            ext_buildings[b["id"]] = {
                "template": t,
                "actor": e.text("VisualActor/Actor"),
                "foundation": e.text("VisualActor/FoundationActor"),
                "icon": e.text("Identity/Icon"),
                "specific_name": e.text("Identity/SpecificName"),
                "footprint": footprint(e),
            }
        heroes = []
        for path in sorted(glob.glob(os.path.join(z.sim, "templates", "units", civ, "hero_*.xml"))):
            t = f"units/{civ}/{os.path.basename(path)[:-4]}"
            if re.search(r"_(infantry|cavalry|elephant|chariot)$", t) or not z.has_template(t):
                continue
            try:
                e = z.entity(t)
            except Exception:  # noqa: BLE001 - a broken template is skipped, not fatal
                continue
            heroes.append({"id": t.split("/")[-1], "name": e.text("Identity/SpecificName") or e.text("Identity/GenericName"),
                           "title": e.text("Identity/GenericName"), "icon": e.text("Identity/Icon"),
                           "history": first_sentences(e.text("Identity/History"), 200)})
        ext_tribes[civ] = {
            "emblem": p.text("Identity/Icon"),
            "buildings": ext_buildings,
            "units": ext_units,
            "heroes": heroes,
        }

    buildings = [building_rules(z, b, civs) for b in cfg["buildings"]]
    pk = cfg["pack"]
    pack = {
        "id": pk["id"],
        "name": pk["name"],
        "version": pk["version"],
        "description": " ".join(pk["description"].split()),
        "world": pk["world"],
        "resources": cfg["resources"],
        "village": cfg["village"],
        "buildings": buildings,
        "tribes": tribes,
        "units": units,
        "combat": cfg["combat"],
        "culture": cfg.get("culture", {}),
        "techs": [{k: v for k, v in t.items() if k != "icon"} for t in cfg.get("techs", [])],
        "extensions": {
            **cfg.get("extensions", {}),
            "zeroad": {
                "source": cfg["source"],
                "tribes": ext_tribes,
                "techs": {t["id"]: f"technologies/{t['icon']}" for t in cfg.get("techs", []) if t.get("icon")},
            },
        },
    }
    return pack


def footprint(e: Entity) -> list[float] | None:
    sq = e.node.find("Footprint/Square")
    if sq is not None:
        return [float(sq.get("width", 0)), float(sq.get("depth", 0))]
    ci = e.node.find("Footprint/Circle")
    if ci is not None:
        r = float(ci.get("radius", 0))
        return [2 * r, 2 * r]
    return None


def building_rules(z: ZeroAD, b: dict, civs: list[str]) -> dict:
    out = {k: v for k, v in b.items() if k not in ("zeroad", "cost")}
    cost = b["cost"]
    mix = cost.get("mix")
    if not mix:
        acc: dict[str, float] = {}
        for civ in civs:
            first = b["zeroad"][0] if isinstance(b["zeroad"], list) else b["zeroad"]
            t = f"structures/{civ}/{first}"
            if z.has_template(t):
                for r, v in z.entity(t).costs().items():
                    acc[r] = acc.get(r, 0) + v
        mix = acc or {"wood": 1}
    s = sum(mix.values())
    base = {r: r5(cost["total"] * mix.get(r, 0) / s) for r in ("food", "wood", "stone", "metal") if mix.get(r, 0) > 0}
    out["cost"] = {"base": base, "factor": cost["factor"]}
    if "speed_exponent" in cost:
        out["cost"]["speed_exponent"] = cost["speed_exponent"]
    order = ["id", "name", "description", "slot", "foreign", "max_level", "unique", "requires", "cost", "time", "population", "effects"]
    return {k: out[k] for k in order if k in out}


def first_sentences(text: str, limit: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for p in parts:
        if out and len(out) + len(p) > limit:
            break
        out = f"{out} {p}".strip()
    return out


HEADER = """\
# Ovian "antiquity" content pack, GENERATED by tools/zeroad/convert.py. Do not edit by hand:
# change tools/zeroad/antiquity.yaml and run tools/zeroad/convert.sh.
#
# Unit and civilization data is derived from 0 A.D. by Wildfire Games
# (https://play0ad.com), {repo} at {commit},
# licensed GPL-2.0-or-later. This file is therefore GPL-2.0-or-later too; see LICENSE in this folder.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zeroad", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--table", action="store_true", help="print a stats table")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    z = ZeroAD(a.zeroad)
    pack = convert(z, cfg)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "pack.yaml"), "w") as f:
        f.write(HEADER.format(**cfg["source"]))
        yaml.safe_dump(pack, f, sort_keys=False, allow_unicode=True, width=110)
    if a.table:
        print(f"{'unit':42} {'cls':4} {'cost':>5} {'att':>4} {'d.inf':>5} {'d.cav':>5} {'spd':>3} {'carry':>5} {'up':>2} {'time':>5}")
        for u in pack["units"]:
            print(f"{u['id']:42} {u['class'][:3]:4} {sum(u['cost'].values()):5} {u['attack']:4} {u['defense']['infantry']:5} {u['defense']['cavalry']:5} {u['speed']:3} {u['carry']:5} {u['upkeep']:2} {u['time']:5}")
    print(f"wrote {len(pack['tribes'])} tribes, {len(pack['units'])} units, {len(pack['buildings'])} buildings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
