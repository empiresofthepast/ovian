from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pluggy
import yaml
from ovian_engine import Engine


@dataclass
class Content:
    engine: Engine
    # The pack as served to clients: engine-normalised, plus "extensions".
    pack: dict[str, Any]

    @property
    def extensions(self) -> dict[str, Any]:
        return self.pack.get("extensions", {})

    def building(self, building_id: str) -> dict[str, Any] | None:
        return next((b for b in self.pack["buildings"] if b["id"] == building_id), None)

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        return next((u for u in self.pack["units"] if u["id"] == unit_id), None)

    def tech(self, tech_id: str) -> dict[str, Any] | None:
        return next((t for t in self.pack.get("techs", []) if t["id"] == tech_id), None)

    def tribe(self, tribe_id: str) -> dict[str, Any] | None:
        return next((t for t in self.pack["tribes"] if t["id"] == tribe_id), None)

    def tribe_ids(self) -> list[str]:
        return [t["id"] for t in self.pack["tribes"]]


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Merge ``over`` into ``base`` (in place): nested dicts merge, anything else is replaced; ``None`` removes a key."""
    for k, v in over.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


OVERRIDABLE = ("world", "village", "buildings", "extensions")


def load_overrides(path: str | None) -> dict[str, Any]:
    """A world's overrides file: ``world``, ``village``, ``buildings`` (a mapping of building id to the
    keys to change) and ``extensions`` may be changed."""
    if not path:
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the overrides must be a mapping")
    unknown = set(data) - set(OVERRIDABLE)
    if unknown:
        raise ValueError(f"{path}: only {', '.join(OVERRIDABLE)} can be overridden, not {sorted(unknown)}")
    if "buildings" in data and not isinstance(data["buildings"], dict):
        raise ValueError(f"{path}: 'buildings' must map building ids to the keys to change")
    return data


def apply_overrides(raw: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Merge an overrides document onto the pack: buildings by id, the rest as nested dicts."""
    for bid, over in (overrides.get("buildings") or {}).items():
        b = next((x for x in raw.get("buildings", []) if x.get("id") == bid), None)
        if b is None:
            raise ValueError(f"overrides: no building {bid!r} in the pack")
        deep_merge(b, over)
    deep_merge(raw, {k: v for k, v in overrides.items() if k != "buildings"})


def _scale_curve(curve: Any, m: float) -> Any:
    if isinstance(curve, dict) and "base" in curve:
        return {**curve, "base": curve["base"] * m}
    if isinstance(curve, list):
        return [x * m for x in curve]
    return curve


def scale_for_speed(raw: dict[str, Any]) -> None:
    """What grows with the world speed, so the numbers of a pack written for speed 1 keep their feel on faster worlds.

    ``village.storage_speed_exponent`` (0 = off): every store's capacity, the base storage and what houses hide are
    multiplied by speed ** exponent, so a store takes about as many real hours to fill at any speed.
    ``cost.speed_exponent`` on a building: its level costs are multiplied by speed ** exponent. Meant for the world
    projects (great buildings, the wonder), whose race would otherwise end in a day on a fast world.
    """
    speed = float((raw.get("world") or {}).get("speed") or 1)
    if speed == 1:
        return
    village = raw.get("village") or {}
    k = float(village.get("storage_speed_exponent") or 0)
    if k:
        m = speed**k
        if "base_storage" in village:
            village["base_storage"] = round(village["base_storage"] * m)
        for b in raw.get("buildings", []):
            eff = b.get("effects") or {}
            if isinstance(eff.get("storage"), dict) and "curve" in eff["storage"]:
                eff["storage"]["curve"] = _scale_curve(eff["storage"]["curve"], m)
            if "hide" in eff:
                eff["hide"] = _scale_curve(eff["hide"], m)
    for b in raw.get("buildings", []):
        cost = b.get("cost") or {}
        e = float(cost.get("speed_exponent") or 0)
        if e and isinstance(cost.get("base"), dict):
            m = speed**e
            cost["base"] = {r: round(v * m) for r, v in cost["base"].items()}


def load_content(content_dir: str, pm: pluggy.PluginManager, world_speed: float | None = None, overrides_file: str | None = None) -> Content:
    path = Path(content_dir) / "pack.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    pm.hook.ovian_pack_loaded(pack=raw)
    overrides = load_overrides(overrides_file)
    if overrides:
        apply_overrides(raw, overrides)
    if world_speed:
        raw.setdefault("world", {})["speed"] = world_speed
    scale_for_speed(raw)
    engine = Engine(raw)
    pack = engine.pack()
    pack["extensions"] = copy.deepcopy(raw.get("extensions", {}))
    return Content(engine=engine, pack=pack)
