"""Check the Wikipedia titles of a pack config (``extensions.wikipedia`` and ``extensions.cultures``) against Wikipedia.

    docker run --rm --network host -v "$PWD:/srv/ovian" -w /srv/ovian ovian-zeroad python3 tools/zeroad/wikicheck.py tools/zeroad/antiquity.yaml

Reports titles with no article, disambiguation pages and redirects (write the target instead), so every link lands.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

import yaml

API = "https://en.wikipedia.org/w/api.php"
AGENT = "ovian-wikicheck/1.0 (https://github.com/empiresofthepast/ovian)"


def titles_of(cfg: dict) -> dict[str, list[str]]:
    ext = cfg.get("extensions", {})
    out: dict[str, list[str]] = {}
    for kind in ("buildings", "units"):
        for k, t in ext.get("wikipedia", {}).get(kind, {}).items():
            out.setdefault(t, []).append(f"wikipedia.{kind}.{k}")
    for civ, c in ext.get("cultures", {}).items():
        for b, e in c.get("buildings", {}).items():
            out.setdefault(e["wikipedia"], []).append(f"cultures.{civ}.{b}")
    return out


def query(titles: list[str]) -> dict:
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join(titles), "redirects": 1, "format": "json",
                                "prop": "pageprops", "ppprop": "disambiguation"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["query"]


def main() -> int:
    cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
    titles = titles_of(cfg)
    names = sorted(titles)
    missing, disamb, redirects = [], [], {}
    for i in range(0, len(names), 50):
        data = query(names[i:i + 50])
        for r in data.get("redirects", []):
            redirects[r["from"]] = r["to"]
        for p in data["pages"].values():
            if "missing" in p or "invalid" in p:
                missing.append(p["title"])
            elif "disambiguation" in p.get("pageprops", {}):
                disamb.append(p["title"])
    print(f"{len(names)} titles checked")
    for label, found in (("missing", missing), ("disambiguation", disamb)):
        for t in sorted(found):
            print(f"{label}: {t!r} ({', '.join(titles[t])})")
    for a, b in sorted(redirects.items()):
        print(f"redirect: {a!r} -> {b!r} ({', '.join(titles[a])})")
    return 1 if missing or disamb or redirects else 0


if __name__ == "__main__":
    sys.exit(main())
