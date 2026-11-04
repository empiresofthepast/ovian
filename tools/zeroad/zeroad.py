"""Readers for 0 A.D. data files: entity templates (simulation) and actors (art).

Only the parts Ovian needs are implemented. Template inheritance follows the
engine's CTemplateLoader semantics closely enough for stats: `parent="a|b"`
loads `b`, layers mixin `a` on top, then the file itself; children merge
recursively; `datatype="tokens"` lists merge with `-token` removals;
`replace`, `disable`, `merge` and `op="add|mul|mul_round"` are honoured.
"""

from __future__ import annotations

import copy
import functools
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

PUBLIC = "binaries/data/mods/public"


class ZeroAD:
    def __init__(self, root: str):
        self.root = root
        self.sim = os.path.join(root, PUBLIC, "simulation")
        self.art = os.path.join(root, PUBLIC, "art")

    # ------------------------------------------------------------------ templates
    def template_path(self, name: str) -> str:
        return os.path.join(self.sim, "templates", name + ".xml")

    def has_template(self, name: str) -> bool:
        return os.path.exists(self.template_path(name))

    @functools.lru_cache(maxsize=None)
    def template(self, name: str) -> ET.Element:
        """Fully resolved template as an element tree (do not mutate)."""
        node = ET.parse(self.template_path(name)).getroot()
        parent = node.get("parent")
        if parent:
            base = self._layered(parent)
            return _merge(base, node)
        return _strip(node)

    def _layered(self, parent: str) -> ET.Element:
        if "|" not in parent:
            return copy.deepcopy(self.template(self._name(parent)))
        mixin, rest = parent.split("|", 1)
        base = self._layered(rest)
        name = self._name(mixin)
        if not self.has_template(name):
            return base
        layer = ET.parse(self.template_path(name)).getroot()
        if layer.get("parent"):
            layer = _merge(self._layered(layer.get("parent")), layer)
        return _merge(base, layer)

    def _name(self, name: str) -> str:
        return name if self.has_template(name) or not self.has_template(f"mixins/{name}") else f"mixins/{name}"

    def entity(self, name: str) -> "Entity":
        return Entity(name, self.template(name))

    # ------------------------------------------------------------------ actors
    def actor_path(self, name: str) -> str:
        return os.path.join(self.art, "actors", name)

    def has_actor(self, name: str) -> bool:
        return os.path.exists(self.actor_path(name))


def _strip(node: ET.Element) -> ET.Element:
    node = copy.deepcopy(node)
    for el in node.iter():
        for a in ("parent",):
            el.attrib.pop(a, None)
    return node


def _tokens(text: str | None) -> list[str]:
    return (text or "").split()


def _merge(base: ET.Element, over: ET.Element) -> ET.Element:
    """Merge `over` onto a copy of `base` (both trees of the same tag)."""
    out = copy.deepcopy(base)
    _merge_into(out, over)
    out.attrib.pop("parent", None)
    return out


def _merge_into(dst: ET.Element, src: ET.Element) -> None:
    for k, v in src.attrib.items():
        if k in ("parent", "replace", "merge", "op", "filtered"):
            continue
        dst.set(k, v)
    if src.get("datatype") == "tokens":
        if src.get("replace") is not None:
            items = []
        else:
            items = _tokens(dst.text)
        for t in _tokens(src.text):
            if t.startswith("-"):
                items = [x for x in items if x != t[1:]]
            elif t not in items:
                items.append(t)
        dst.text = " ".join(items)
    elif src.get("op") and (src.text or "").strip():
        try:
            a, b = float((dst.text or "0").strip() or 0), float(src.text.strip())
            op = src.get("op")
            r = a + b if op == "add" else a * b
            if op == "mul_round":
                r = round(r)
            dst.text = repr(r)
        except ValueError:
            dst.text = src.text
    elif (src.text or "").strip():
        dst.text = src.text
    if src.get("filtered") is not None:
        keep = {c.tag for c in src}
        for c in list(dst):
            if c.tag not in keep:
                dst.remove(c)
    for child in src:
        existing = dst.find(child.tag)
        if child.get("disable") is not None:
            if existing is not None:
                dst.remove(existing)
            continue
        if child.get("replace") is not None and child.get("datatype") != "tokens":
            if existing is not None:
                dst.remove(existing)
            fresh = copy.deepcopy(child)
            fresh.attrib.pop("replace", None)
            dst.append(fresh)
            continue
        if existing is None:
            if child.get("merge") is not None:
                continue  # merge-only: skip when the parent has no such node
            fresh = ET.Element(child.tag)
            dst.append(fresh)
            existing = fresh
        _merge_into(existing, child)


@dataclass
class Entity:
    """Convenience accessors over a resolved entity template."""

    name: str
    node: ET.Element

    def text(self, path: str, default: str = "") -> str:
        el = self.node.find(path)
        return (el.text or "").strip() if el is not None and el.text else default

    def num(self, path: str, default: float = 0.0) -> float:
        t = self.text(path)
        try:
            return float(t) if t else default
        except ValueError:
            return default

    def tokens(self, path: str) -> list[str]:
        el = self.node.find(path)
        return _tokens(el.text) if el is not None else []

    def has(self, path: str) -> bool:
        return self.node.find(path) is not None

    @property
    def classes(self) -> set[str]:
        return set(self.tokens("Identity/Classes")) | set(self.tokens("Identity/VisibleClasses"))

    @property
    def civ(self) -> str:
        return self.text("Identity/Civ")

    def costs(self) -> dict[str, float]:
        res = self.node.find("Cost/Resources")
        if res is None:
            return {}
        return {c.tag: float(c.text) for c in res if c.text and float(c.text) > 0}

    def damage(self, path: str) -> dict[str, float]:
        el = self.node.find(path)
        if el is None:
            return {}
        return {c.tag: float(c.text) for c in el if c.text and c.text.strip()}

    def bonuses(self, attack: str) -> list[tuple[set[str], float]]:
        """(required classes, multiplier) pairs of an attack's Bonuses."""
        out = []
        el = self.node.find(f"Attack/{attack}/Bonuses")
        for b in el if el is not None else []:
            classes = set(_tokens(b.findtext("Classes")))
            mult = float(b.findtext("Multiplier") or 1)
            out.append((classes, mult))
        return out


# ---------------------------------------------------------------------- actors


@dataclass
class Look:
    """One concrete appearance of an actor: a mesh, its textures and props."""

    mesh: str | None = None
    textures: dict[str, str] = field(default_factory=dict)
    props: list[tuple[str, str]] = field(default_factory=list)  # (attachpoint, actor)
    decal: dict | None = None
    color: list[float] | None = None


SKIP_VARIANTS = ("destruction", "death", "dead", "garrison", "fire", "burn", "ruin", "carry", "gather", "attack", "packed", "winter")


def _parse_variant(z: ZeroAD, el: ET.Element) -> list[dict]:
    """A variant's layers in apply order: its `file=` include first, then itself."""
    layers = []
    if el.get("file"):
        p = os.path.join(z.art, "variants", el.get("file"))
        if os.path.exists(p):
            inc = ET.parse(p).getroot()
            layers.extend(_parse_variant(z, inc))
    layer: dict = {}
    mesh = el.find("mesh")
    if mesh is not None and mesh.text:
        layer["mesh"] = mesh.text.strip()
    tex = el.find("textures")
    if tex is not None:
        layer["textures"] = {t.get("name", "baseTex"): t.get("file") for t in tex if t.get("file")}
    props = el.find("props")
    if props is not None:
        layer["props"] = [(p.get("attachpoint", "root"), p.get("actor", "")) for p in props]
    decal = el.find("decal")
    if decal is not None:
        layer["decal"] = {k: float(v) for k, v in decal.attrib.items()}
    color = el.find("color")
    if color is not None and color.text:
        try:
            layer["color"] = [float(c) / 255 for c in color.text.split()]
        except ValueError:
            pass
    layers.append(layer)
    return layers


def _apply(look: Look, layer: dict) -> None:
    if "mesh" in layer:
        look.mesh = layer["mesh"]
    look.textures.update(layer.get("textures", {}))
    if "props" in layer:
        points = {p for p, _ in layer["props"]}
        look.props = [p for p in look.props if p[0] not in points]
        look.props.extend((p, a) for p, a in layer["props"] if a)
    if "decal" in layer:
        look.decal = layer["decal"]
    if "color" in layer:
        look.color = layer["color"]


@dataclass
class Actor:
    name: str
    looks: list[Look]
    material: str
    castshadow: bool
    float: bool


def load_actor(z: ZeroAD, name: str, max_looks: int = 4) -> Actor:
    """Resolve an actor into up to `max_looks` idle appearances.

    The first group with several real choices supplies the alternatives (trees
    and rocks vary there); every other group contributes its idle default.
    """
    root = ET.parse(z.actor_path(name)).getroot()
    groups = []
    for g in root.findall("group"):
        vs = [v for v in g.findall("variant")]
        groups.append(vs)

    def weight(v: ET.Element) -> float:
        return float(v.get("frequency", "0") or 0)

    def idle(vs: list[ET.Element]) -> list[ET.Element]:
        named_ok = [v for v in vs if not any(s in (v.get("name") or "").lower() for s in SKIP_VARIANTS)]
        weighted = [v for v in named_ok if weight(v) > 0] or named_ok[:1] or vs[:1]
        return weighted

    choices = [idle(vs) for vs in groups if vs]
    vary = next((i for i, c in enumerate(choices) if len(c) > 1), None)
    n = min(max_looks, len(choices[vary])) if vary is not None else 1
    looks = []
    for k in range(n):
        look = Look()
        for i, c in enumerate(choices):
            v = c[k] if i == vary else max(c, key=weight)
            for layer in _parse_variant(z, v):
                _apply(look, layer)
        looks.append(look)
    material = (root.findtext("material") or "default.xml").strip()
    return Actor(name, looks, material, root.find("castshadow") is not None, root.find("float") is not None)


def material_kind(material: str) -> str:
    m = material.lower()
    if m.startswith("player_trans"):
        return "player"
    if m.startswith("objectcolor"):
        return "objectcolor"
    if "trans" in m and not m.startswith("no_trans"):
        return "alphatest"
    if "blend" in m or "aura" in m or "glow" in m:
        return "blend"
    return "opaque"
