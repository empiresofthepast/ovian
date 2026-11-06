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


def load_overrides(path: str | None) -> dict[str, Any]:
    """A world's overrides file: only ``world`` and ``extensions`` may be changed."""
    if not path:
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the overrides must be a mapping")
    unknown = set(data) - {"world", "extensions"}
    if unknown:
        raise ValueError(f"{path}: only 'world' and 'extensions' can be overridden, not {sorted(unknown)}")
    return data


def load_content(content_dir: str, pm: pluggy.PluginManager, world_speed: float | None = None, overrides_file: str | None = None) -> Content:
    path = Path(content_dir) / "pack.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    pm.hook.ovian_pack_loaded(pack=raw)
    overrides = load_overrides(overrides_file)
    if overrides:
        deep_merge(raw, overrides)
    if world_speed:
        raw.setdefault("world", {})["speed"] = world_speed
    engine = Engine(raw)
    pack = engine.pack()
    pack["extensions"] = copy.deepcopy(raw.get("extensions", {}))
    return Content(engine=engine, pack=pack)
