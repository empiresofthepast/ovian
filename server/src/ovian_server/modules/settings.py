"""What a world can be tuned with: the catalogue of pack extension groups, their code defaults, and the mode presets.

``GET /settings/schema`` (public) lists every group a module reads from ``extensions`` with the defaults used when the
pack says nothing, whether leaving the group out switches the feature off, a one-line meaning, and the values this
world runs with. ``GET /settings/modes`` lists the presets a spawned world can start from (hybrid, pve, pvp): each is
an *overrides* document (``{world, extensions}``) merged onto the pack by ``content.load_content``; ``null`` removes a
group, which turns a switchable feature off. The hub's world spawner shows both to its administrators.

The catalogue mirrors the modules' own defaults (surveyed 2026-11-06); modules that expose ``DEFAULTS`` are imported.
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter

from ..deps import GameDep
from .base import Module

router = APIRouter(tags=["settings"])


def _defaults(module: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        mod = __import__(f"ovian_server.modules.{module}", fromlist=["DEFAULTS"])
        return copy.deepcopy(getattr(mod, "DEFAULTS"))
    except (ImportError, AttributeError):
        return fallback


# group -> (what it controls, defaults when the pack omits it, whether leaving it out switches the feature off)
GROUPS: dict[str, dict[str, Any]] = {
    "abandon": {"doc": "Cities of players not seen for `days` days fall to the barbarians (ruins).", "off_when_absent": True,
                "defaults": {"days": 7, "every_minutes": 60, "per_level": 400}},
    "archaeology": {"doc": "Building layers, digs, finds and camp spoils; finds shown in temples give culture.", "off_when_absent": True,
                    "defaults": {"hours": 2, "ancient_chance": 0.4, "camp_find_chance": 0.05, "camp_find_max": 0.3, "cost": {},
                                 "display": {"building": "temple", "per_level": 1}, "grades": {"common": {"chance": 1, "culture": 1}}, "ancient": [], "finds": {}}},
    "artworks": {"doc": "Statues commissioned from famous sculptors, kept as finds that always count for culture.", "off_when_absent": False,
                 "defaults": _defaults("artworks", {})},
    "auxiliaries": {"doc": "An overlord levies a vassal's own units into its garrison (needs embassies).", "off_when_absent": True,
                    "defaults": {"cost": 1.25, "mood_per_100": -3.0, "mood_max": -15.0, "mood_hours": 24.0}},
    "beginner_protection_hours": {"doc": "Hours a new player cannot be attacked, raided or scouted (a number, not a group).", "off_when_absent": True,
                                  "defaults": 0},
    "camps": {"doc": "Barbarian camps: how many, how strong, their loot and how fast they recover.", "off_when_absent": False,
              "defaults": {"count": 12, "min_distance": 4, "max_distance": 16, "max_level": 5, "troops_per_level": 12, "regen": 3600, "loot_per_level": 1500}},
    "chronicle": {"doc": "The public world history and the GeoJSON projection of the grid; `battle_units` is the size worth recording.", "off_when_absent": False,
                  "defaults": {"geo": {"lon": 12.0, "lat": 42.0, "deg_per_tile": 0.05, "real": False}, "battle_units": 150}},
    "cities": {"doc": "Least distance between two cities when a city is placed.", "off_when_absent": False, "defaults": {"min_distance": 3}},
    "contentment": {"doc": "City contentment: production bonus or penalty, citizens' defense, vassal unrest and rebellion.", "off_when_absent": True,
                    "defaults": {"base": 5, "culture_divisor": 5, "culture_max": 20, "amenities_max": 30, "food_surplus": 5, "food_deficit": -20,
                                 "size_per_level": -0.5, "tribute": -15, "colony": -5, "defeat": -5, "defeat_hours": 24, "defeat_max": -20,
                                 "bonus_per_point": 0.002, "bonus_max": 0.1, "penalty_per_point": 0.004, "penalty_max": 0.4, "rebel_below": -10,
                                 "rebel_at": 100, "calm_rate": 10, "tick_minutes": 30, "defense_from": 50, "defense_per_point": 0.004, "defense_max": 0.2, "techs": {}}},
    "demolish": {"doc": "Share of the cost refunded when a building is pulled down, and buildings that cannot be.", "off_when_absent": False,
                 "defaults": {"refund": 0.5, "keep": []}},
    "embassies": {"doc": "The foreign quarter in vassal cities (embassy, exchange), tribute relief, stewardship, ruins.", "off_when_absent": True,
                  "defaults": {"building": "embassy", "ruin": "ruin", "exchange": "exchange", "exchange_slots": 1, "exchange_relief": 0.03,
                               "overlord": [], "overlord_slots": 0, "steward_level": 0}},
    "festival": {"doc": "The yearly festival: contests with prizes and medals (needs seasons).", "off_when_absent": True,
                 "defaults": {"name": "Festival", "text": "", "season": None, "prizes": [], "contests": {}}},
    "gods": {"doc": "Temple favor and divine powers.", "off_when_absent": False,
             "defaults": {"building": "temple", "favor_per_level": 2, "max_favor": 500, "powers": {}}},
    "governments": {"doc": "Player-wide governments with effects, a cooldown between changes and a spell of anarchy.", "off_when_absent": True,
                    "defaults": {"default": None, "list": {}, "cooldown_hours": 48, "anarchy_hours": 6, "anarchy": {"contentment": -15, "production": {"all": -0.1}}}},
    "governors": {"doc": "Hiring and appointing named governors and prefects with traits.", "off_when_absent": True,
                  "defaults": {"hire": {}, "candidates": 3, "refresh_hours": 24, "speed": 8, "prefect": None, "traits": {}, "names": {}}},
    "great_buildings": {"doc": "Buildings anyone may contribute to; contributors get `reward` of their gift back.", "off_when_absent": True,
                        "defaults": {"buildings": [], "reward": 0.5}},
    "heroes": {"doc": "Hero experience and levels, bonuses per point, revive time (seconds) and travel speed.", "off_when_absent": False,
               "defaults": {"xp_base": 100, "attack_per_point": 0.03, "defense_per_point": 0.03, "production_per_point": 0.02, "revive": 14400, "speed": 10}},
    "horde": {"doc": "A barbarian horde gathers against the strongest active player every `every_hours` (real hours).", "off_when_absent": True,
              "defaults": {"every_hours": 24, "warning_hours": 3, "ratio": 1.0, "min_troops": 150, "active_days": 3}},
    "market": {"doc": "Merchants: what they carry and how fast they go, per market level.", "off_when_absent": False,
               "defaults": {"building": "market", "carry": 1000, "speed": 12}},
    "medals": {"doc": "Periodic gold, silver and bronze medals per category; the hall of fame.", "off_when_absent": False,
               "defaults": {"period_hours": 168, "places": 3, "categories": ["attacker", "defender", "raider", "builder", "trader"]}},
    "militia": {"doc": "Citizens fight as defenders once a militia tech is researched.", "off_when_absent": True, "defaults": {"techs": {}, "units": {}}},
    "night": {"doc": "Defenders fight better at night (UTC hours).", "off_when_absent": True, "defaults": {"start": 0, "end": 6, "defense": 0.25}},
    "omens": {"doc": "Random city events with choices (moods, boosts, favor, statues).", "off_when_absent": True,
              "defaults": {"chance": 0.35, "every_hours": 6, "expire_hours": 12, "events": "built in"}},
    "pvp": {"doc": "`enabled: false` forbids attacks, raids and scouting against other players: a PvE world.", "off_when_absent": False,
            "defaults": {"enabled": True}},
    "quests": {"doc": "The quest and tutorial chain (a list of quests).", "off_when_absent": True, "defaults": []},
    "quests_visible": {"doc": "How many unclaimed quests are shown at once (a number).", "off_when_absent": False, "defaults": 3},
    "ranks": {"doc": "Techs that make a city's troops better soldiers (tech -> fraction).", "off_when_absent": True, "defaults": {}},
    "roads": {"doc": "Roads between own or vassal cities that speed travel up.", "off_when_absent": True,
              "defaults": {"cost_per_tile": {}, "seconds_per_tile": 900, "speed": 1.5, "base": 1, "per_levels": 10, "max_length": 30}},
    "scouting": {"doc": "Scouts' chances and the sabotage, steal and incite missions.", "off_when_absent": False,
                 "defaults": {"stealth": 10, "missions": {"sabotage": {"difficulty": 2}, "steal": {"difficulty": 3}, "incite": {"difficulty": 2, "unrest": 40}}}},
    "seasons": {"doc": "Rotating seasons with production, travel and contentment effects.", "off_when_absent": True, "defaults": {"hours": 24, "list": []}},
    "settlers": {"doc": "Settlers turn a beaten camp into a colony; their price grows with cities and settlers held.", "off_when_absent": True,
                 "defaults": {"unit": None, "price_growth": 1.5}},
    "starvation": {"doc": "Troops die when the upkeep resource runs out.", "off_when_absent": True, "defaults": {"tick_hours": 1.0, "share": 0.25}},
    "submission": {"doc": "Repeated wins make vassals: tribute, protection benefits, voluntary fealty, overlord taxes.", "off_when_absent": False,
                   "defaults": {"wins": 5, "tribute": 0.1, "kinds": ["attack", "raid"], "benefits": {"production": 0.05, "defense": 0.15, "contentment": 5.0, "trade_speed": 0.5},
                                "voluntary": {"tribute": 0.05}, "taxes": {"min": 0.0, "max": 0.3, "per_point": 1.0, "distance": 15.0}}},
    "terrain": {"doc": "More stone by the mountains and hills, more wood by the forests.", "off_when_absent": False, "defaults": _defaults("terrain", {})},
    "trade": {"doc": "Merchants earn a profit abroad and risk bandits off the roads.", "off_when_absent": True,
              "defaults": {"profit_per_tile": 0.01, "profit_max": 0.25, "profit_cap_per_level": 2000, "bandits_from": 6, "bandits_per_tile": 0.02, "bandits_max": 0.3, "bandits_take": 0.5}},
    "trade_routes": {"doc": "Recurring shipments between cities.", "off_when_absent": False, "defaults": {"max_per_city": 5, "min_hours": 1}},
    "treaties": {"doc": "Peace pacts with optional tribute; oath-breakers are marked and their cities unhappy.", "off_when_absent": False,
                 "defaults": {"notice_hours": 6, "treachery_hours": 48, "treachery_mood": -15, "min_tribute_hours": 1}},
    "vacation": {"doc": "How long a vacation shield may last.", "off_when_absent": False, "defaults": {"min_hours": 12, "max_days": 14}},
    "ver_sacrum": {"doc": "A city sends migrants to found a colony every `every` growth levels.", "off_when_absent": False,
                   "defaults": {"every": 10, "range_per_level": 0.5, "speed": 6.0, "tribute": 0.1, "cost": {}}},
    "victory": {"doc": "Ways to win the world; `false` drops a condition.", "off_when_absent": False, "defaults": {"conditions": _defaults("victory", {})}},
    "wonder": {"doc": "Which building is the wonder.", "off_when_absent": False, "defaults": {"building": "wonder"}},
    "zeroad": {"doc": "Per-civilization hero candidates from the 0 A.D. data.", "off_when_absent": False, "defaults": {"tribes": {}}},
}

WORLD_KEYS: dict[str, Any] = {"doc": "The map and the clock: `width`, `height`, `seed`, `generator` (grid | islands) and `speed`.",
                              "defaults": {"width": 121, "height": 121, "seed": 1177, "generator": "grid", "speed": 1}}

# Presets a spawned world starts from: overrides documents. null removes a group (turning a switchable feature off).
MODES: dict[str, dict[str, Any]] = {
    "hybrid": {"name": "Hybrid", "doc": "The pack as it is: players fight each other and the barbarians.", "overrides": {}},
    "pve": {"name": "PvE", "doc": "No war between players: camps, the horde, quests and the wonder, culture and conquest races.",
            "overrides": {"extensions": {
                "pvp": {"enabled": False}, "treaties": None, "night": None,
                "camps": {"count": 24, "max_level": 6}, "horde": {"every_hours": 12, "ratio": 1.2},
                "beginner_protection_hours": 168,
                "victory": {"conditions": {"battles": False}}}}},
    "pvp": {"name": "PvP", "doc": "War between players: no camps or horde, short protection, faster abandonment, battles count toward victory.",
            "overrides": {"extensions": {
                "camps": {"count": 0}, "horde": None, "abandon": {"days": 3},
                "beginner_protection_hours": 24, "treaties": {"treachery_hours": 72},
                "victory": {"conditions": {"battles": {"wins": 1000}, "conquest": {"cities": 20}}}}}},
}


def schema(current: dict[str, Any] | None = None, world: dict[str, Any] | None = None) -> dict[str, Any]:
    groups = []
    for key, g in GROUPS.items():
        entry = {"key": key, "doc": g["doc"], "off_when_absent": g["off_when_absent"], "defaults": g["defaults"]}
        if current is not None:
            entry["current"] = current.get(key)
            entry["present"] = key in current
        groups.append(entry)
    out: dict[str, Any] = {"world": {**WORLD_KEYS, **({"current": world} if world is not None else {})}, "groups": groups}
    return out


@router.get("/settings/schema")
async def settings_schema(game: GameDep) -> dict[str, Any]:
    """Every tunable group with its code defaults and this world's values."""
    return schema(game.content.extensions, {k: game.content.pack["world"].get(k) for k in WORLD_KEYS["defaults"]})


@router.get("/settings/modes")
async def settings_modes() -> dict[str, Any]:
    """The presets a new world can start from, as overrides documents."""
    return MODES


module = Module("settings", router=router)
