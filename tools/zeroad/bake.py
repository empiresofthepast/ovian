"""Bake 0 A.D. art for the diorama front end.

    python bake.py --zeroad /cache/repo --config diorama.yaml --content ../../content --out <dir>

Writes:
  manifest.json   actors (looks, props, materials), per-pack mapping, icons
  m/...           COLLADA meshes, image libraries stripped
  t/...           textures as WebP, at most `max_texture` pixels on a side
  ui/...          HUD icons, portraits and emblems as WebP
  ATTRIBUTION.txt licence and source of every file here
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import yaml
from PIL import Image

from zeroad import Actor, ZeroAD, load_actor, material_kind

Image.MAX_IMAGE_PIXELS = None
SKIP_POINTS = ("projectile", "garrison", "loaded", "fire", "smoke")


class Baker:
    def __init__(self, z: ZeroAD, cfg: dict, out: str):
        self.z, self.cfg, self.out = z, cfg, out
        self.actors: dict[str, dict] = {}
        self.meshes: set[str] = set()
        self.textures: set[str] = set()
        self.ui: dict[str, str] = {}  # source path under art/textures/ui -> output name
        self.missing: list[str] = []

    # -------------------------------------------------------------- collection
    def actor(self, name: str | None) -> str | None:
        """Queue an actor (and its props, recursively); returns its id or None."""
        if not name:
            return None
        name = name if name.endswith(".xml") else name + ".xml"
        aid = name[:-4]
        if aid in self.actors:
            return aid
        if not self.z.has_actor(name):
            self.missing.append(f"actor {name}")
            return None
        self.actors[aid] = {}  # placeholder against cycles
        a: Actor = load_actor(self.z, name)
        looks = []
        for look in a.looks:
            entry: dict = {}
            if look.mesh and self._mesh(look.mesh):
                entry["mesh"] = look.mesh
            tex = look.textures.get("baseTex") or next(iter(look.textures.values()), None)
            if tex:
                t = self._texture(tex)
                if t:
                    entry["tex"] = t
            props = []
            for point, child in look.props:
                if any(x in point for x in SKIP_POINTS):
                    continue
                cid = self.actor(child)
                if cid and self.actors.get(cid) != {"empty": True}:
                    props.append([point, cid])
            if props:
                entry["props"] = props
            if look.decal:
                entry["decal"] = look.decal
            if look.color:
                entry["color"] = look.color
            if entry:
                looks.append(entry)
        if not looks:
            self.actors[aid] = {"empty": True}
            return aid
        self.actors[aid] = {"looks": looks, "mat": material_kind(a.material), "shadow": a.castshadow}
        return aid

    def _mesh(self, rel: str) -> bool:
        if os.path.exists(os.path.join(self.z.art, "meshes", rel)):
            self.meshes.add(rel)
            return True
        self.missing.append(f"mesh {rel}")
        return False

    def _texture(self, rel: str) -> str | None:
        base = os.path.join(self.z.art, "textures", "skins")
        stem, _ = os.path.splitext(rel)
        for ext in (os.path.splitext(rel)[1], ".dds", ".png", ".tga"):
            if os.path.exists(os.path.join(base, stem + ext)):
                self.textures.add(stem + ext)
                return stem
        self.missing.append(f"texture {rel}")
        return None

    def ui_icon(self, rel: str | None, kind: str = "") -> str | None:
        """Queue a UI texture (path under art/textures/ui/); returns its output path."""
        if not rel:
            return None
        src = os.path.join(kind, rel) if kind else rel
        if not os.path.exists(os.path.join(self.z.art, "textures", "ui", src)):
            self.missing.append(f"ui {src}")
            return None
        out = "ui/" + os.path.splitext(src)[0] + ".webp"
        self.ui[src] = out
        return out

    # -------------------------------------------------------------- writing
    def write(self) -> None:
        jobs = []
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            for rel in sorted(self.meshes):
                jobs.append(pool.submit(self._write_mesh, rel))
            for rel in sorted(self.textures):
                jobs.append(pool.submit(self._write_texture, rel))
            for src, out in sorted(self.ui.items()):
                jobs.append(pool.submit(self._write_ui, src, out))
            for j in jobs:
                j.result()

    def _write_mesh(self, rel: str) -> None:
        dst = os.path.join(self.out, "m", rel)
        if _fresh(dst):
            return
        text = open(os.path.join(self.z.art, "meshes", rel), encoding="utf-8", errors="replace").read()
        text = re.sub(r"<library_images>.*?</library_images>", "", text, flags=re.S)
        text = re.sub(r"<library_images\s*/>", "", text)
        text = re.sub(r">\s+<", "><", text)
        # three.js names objects from `name` only; 0 A.D. prop points often carry just an id
        text = re.sub(r'<node id="([^"]+)"(?![^>]*\bname=)', r'<node id="\1" name="\1"', text)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
        with gzip.open(dst + ".gz", "wb", compresslevel=9) as f:  # served as-is by nginx gzip_static
            f.write(text.encode())

    def _write_texture(self, rel: str) -> None:
        dst = os.path.join(self.out, "t", os.path.splitext(rel)[0] + ".webp")
        if _fresh(dst):
            return
        try:
            im = Image.open(os.path.join(self.z.art, "textures", "skins", rel))
            im.load()
        except Exception as e:  # noqa: BLE001 - report and keep baking
            self.missing.append(f"texture {rel} ({e})")
            return
        im = im.convert("RGBA")
        m = self.cfg.get("max_texture", 1024)
        if max(im.size) > m:
            im.thumbnail((m, m), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        opaque = im.getextrema()[3][0] == 255
        (im.convert("RGB") if opaque else im).save(dst, "WEBP", quality=82, method=4)

    def _write_ui(self, src: str, out: str) -> None:
        dst = os.path.join(self.out, out)
        if _fresh(dst):
            return
        im = Image.open(os.path.join(self.z.art, "textures", "ui", src)).convert("RGBA")
        if "portraits" in src and max(im.size) > 128:
            im.thumbnail((128, 128), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        im.save(dst, "WEBP", quality=88, method=4)


def _fresh(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def terrain_texture(z: ZeroAD, out: str, rel: str) -> str | None:
    src = os.path.join(z.art, "textures", "terrain", "types", rel)
    if not os.path.exists(src):
        return None
    name = "terrain/" + os.path.splitext(rel)[0] + ".webp"
    dst = os.path.join(out, name)
    if not _fresh(dst):
        im = Image.open(src).convert("RGB")
        if max(im.size) > 512:
            im.thumbnail((512, 512), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        im.save(dst, "WEBP", quality=85)
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zeroad", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--content", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    z = ZeroAD(a.zeroad)
    os.makedirs(a.out, exist_ok=True)
    b = Baker(z, cfg, a.out)

    # ---- packs: which civ per tribe, which structure per building
    packs_out: dict[str, dict] = {}
    civs: set[str] = set()
    for pid, pcfg in cfg["packs"].items():
        path = os.path.join(a.content, pid, "pack.yaml")
        if not os.path.exists(path):
            continue
        pack = yaml.safe_load(open(path))
        zext = pack.get("extensions", {}).get("zeroad")
        # building -> 0 A.D. structure role; a list means "first one the civ has", resolved per tribe
        tribe_buildings: dict[str, dict[str, str]] = {}
        if zext:
            tribes = {t: t for t in zext["tribes"]}
            buildings = {}
            for tid, t in zext["tribes"].items():
                for bid, info in t["buildings"].items():
                    role = info["template"].split("/")[-1]
                    buildings.setdefault(bid, role)
                    tribe_buildings.setdefault(tid, {})[bid] = role
        else:
            tribes, buildings = pcfg["tribes"], {}
            for bid, role in pcfg["buildings"].items():
                roles = role if isinstance(role, list) else [role]
                buildings[bid] = roles[0]
                for tid, civ in tribes.items():
                    have = next((r for r in roles if z.has_template(f"structures/{civ}/{r}")), roles[0])
                    tribe_buildings.setdefault(tid, {})[bid] = have
        kinds = pcfg["resources"]
        fields = {}
        for bd in pack["buildings"]:
            prod = (bd.get("effects") or {}).get("production")
            if bd["slot"] == "field" and prod:
                fields[bd["id"]] = kinds.get(prod["resource"], "food")
        units = {}
        for u in pack.get("units", []):
            civ = tribes.get(u["tribe"])
            info = (zext or {}).get("tribes", {}).get(u["tribe"], {}).get("units", {}).get(u["id"])
            if info:
                units[u["id"]] = {"icon": b.ui_icon(info["icon"], "session/portraits")}
        tech_icons = {}
        all_icons = {**(anti_icons := (yaml.safe_load(open(os.path.join(a.content, "antiquity", "pack.yaml")))
                                       .get("extensions", {}).get("zeroad", {}).get("techs", {}))), **(zext or {}).get("techs", {})}
        for t in pack.get("techs", []):
            if t["id"] in all_icons:
                tech_icons[t["id"]] = b.ui_icon(all_icons[t["id"]], "session/portraits")
        packs_out[pid] = {"tribes": tribes, "buildings": buildings, "tribe_buildings": tribe_buildings, "fields": fields,
                          "resources": kinds, "units": units, "techs": tech_icons}
        civs |= set(tribes.values())

    # classic-style packs borrow unit portraits from the antiquity roster, by class and order
    anti = yaml.safe_load(open(os.path.join(a.content, "antiquity", "pack.yaml")))
    roster: dict[tuple[str, str], list[str]] = {}
    for u in anti["units"]:
        info = anti["extensions"]["zeroad"]["tribes"][u["tribe"]]["units"][u["id"]]
        roster.setdefault((u["tribe"], u["class"]), []).append(info["icon"])
    for pid, p in packs_out.items():
        if p["units"]:
            continue
        pack = yaml.safe_load(open(os.path.join(a.content, pid, "pack.yaml")))
        seen: dict[tuple[str, str], int] = {}
        for u in pack.get("units", []):
            key = (p["tribes"].get(u["tribe"], ""), u["class"])
            icons = roster.get(key) or roster.get((key[0], "infantry")) or []
            i = seen.get(key, 0)
            seen[key] = i + 1
            if icons:
                p["units"][u["id"]] = {"icon": b.ui_icon(icons[min(i, len(icons) - 1)], "session/portraits")}

    # ---- civs: structures, flags, emblems
    civs_out = {}
    for civ in sorted(civs):
        player = z.entity(f"special/players/{civ}")
        structures = {}
        for role in cfg["structures"]:
            t = f"structures/{civ}/{role}"
            if not z.has_template(t):
                continue
            e = z.entity(t)
            aid = b.actor(e.text("VisualActor/Actor"))
            if not aid:
                continue
            sq = e.node.find("Footprint/Square")
            ci = e.node.find("Footprint/Circle")
            fp = [float(sq.get("width")), float(sq.get("depth"))] if sq is not None else ([2 * float(ci.get("radius"))] * 2 if ci is not None else None)
            structures[role] = {
                "actor": aid,
                "foundation": b.actor(e.text("VisualActor/FoundationActor")),
                "footprint": fp,
                "name": e.text("Identity/GenericName"),
                "specific": e.text("Identity/SpecificName"),
                "icon": b.ui_icon(e.text("Identity/Icon"), "session/portraits"),
            }
        anti_civ = anti["extensions"]["zeroad"]["tribes"].get(civ, {})
        civs_out[civ] = {
            "heroes": {h["id"]: b.ui_icon(h["icon"], "session/portraits") for h in anti_civ.get("heroes", []) if h.get("icon")},
            "name": player.text("Identity/GenericName", civ),
            "emblem": b.ui_icon(player.text("Identity/Icon"), "session/portraits"),
            "structures": structures,
            "flag": b.actor(cfg["common"]["rally_flag"].format(civ=civ)),
        }

    # ---- gaia
    gaia = {k: [x for x in (b.actor(n) for n in v) if x] for k, v in cfg["fields"].items()}
    plot = b.actor(cfg["common"]["plot"])
    terrain = {}
    for k, v in cfg["terrain"].items():
        terrain[k] = [terrain_texture(z, a.out, x) for x in v] if isinstance(v, list) else terrain_texture(z, a.out, v)
    icons = {os.path.splitext(os.path.basename(p))[0]: b.ui_icon(p) for p in cfg["ui"]}

    print(f"baking {len(b.actors)} actors, {len(b.meshes)} meshes, {len(b.textures)} textures, {len(b.ui)} ui images", file=sys.stderr)
    b.write()

    manifest = {
        "version": 1,
        "source": cfg["source"],
        "packs": packs_out,
        "civs": civs_out,
        "gaia": gaia,
        "plot": plot,
        "terrain": terrain,
        "icons": icons,
        "actors": {k: v for k, v in sorted(b.actors.items()) if v and not v.get("empty")},
    }
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, separators=(",", ":"))
    with open(os.path.join(a.out, "ATTRIBUTION.txt"), "w") as f:
        f.write(ATTRIBUTION.format(**cfg["source"]))
    if b.missing:
        print(f"{len(b.missing)} missing references (skipped):", file=sys.stderr)
        for m in sorted(set(b.missing))[:40]:
            print("  " + m, file=sys.stderr)
    return 0


ATTRIBUTION = """\
Art in this folder comes from 0 A.D. by Wildfire Games (https://play0ad.com),
{repo} at commit {commit}.

0 A.D. art is licensed under Creative Commons Attribution-ShareAlike 3.0
(https://creativecommons.org/licenses/by-sa/3.0/). The files here were converted
by tools/zeroad/bake.py: meshes are the original COLLADA files with their image
libraries removed, textures were re-encoded as WebP and scaled down, UI images
were re-encoded as WebP. These derived files are shared under the same licence.
"""


if __name__ == "__main__":
    sys.exit(main())
