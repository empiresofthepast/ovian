# Skins

A skin changes how the web client looks and what it calls things. It never changes rules. Skins live in `web/public/skins/<id>/` and are listed in `config.json` (set `OVIAN_SKINS` and `OVIAN_DEFAULT_SKIN` on the web container). Players switch skins in Settings.

The repo ships three skins:

| Skin | Look |
|---|---|
| `parchment` | Warm paper and ink. The default. |
| `nightwatch` | Dark slate and amber, monochrome glyphs, side navigation. |
| `aegean` | Whitewash and sea blue, island vocabulary. Inherits from parchment. |

## Files

```
skins/myskin/
  skin.json     manifest
  theme.css     CSS variables and any extra rules
  icons/...     optional images referenced from skin.json
```

## skin.json

```json
{
  "name": "My Skin",
  "extends": "parchment",
  "author": "you",
  "description": "One line for the settings page.",
  "stylesheet": "theme.css",
  "fonts": ["https://fonts.googleapis.com/css2?family=Cinzel:wght@600&display=swap"],
  "swatches": ["#111", "#eee", "#c33"],
  "layout": { "nav": "side", "hide": ["rankings"] },
  "icons": {
    "resource.wood": "icons/wood.svg",
    "building.farm": "🌾",
    "nav.map": "⌖"
  },
  "labels": {
    "app.title": "My Realm",
    "nav.village": "Holdfast",
    "building.town_hall": "Great Hall",
    "error.queue_full": "Your builders are busy."
  },
  "map": {
    "terrain": { "plain": "#cbd59a", "water": "#6fa3c7" },
    "own": "#1f5fa8", "other": "#9b3b1b", "selected": "#fff", "grid": "rgba(0,0,0,.08)", "label": "#333"
  }
}
```

- **`extends`** inherits icons, labels and map colours from another skin. The stylesheet is not inherited, because the base styles already apply.
- **Icons** are either a text glyph or an image path relative to the skin folder (`.svg`, `.png`, `.webp`, `.gif`, `.jpg`). Keys are `resource.<id>`, `building.<id>`, `unit.<id>`, `tribe.<id>`, `terrain.<id>`, `nav.<feature>`, `stat.<name>`, `slot.empty` and `app.logo`. A missing key falls back to its prefix (`building`) and then to a dot.
- **Labels** override any UI text. Building, unit, resource and tribe names default to the content pack's names. See `web/src/app/core/defaults.ts` for the built-in keys.
- **`layout.nav`** is `top` or `side`. **`layout.hide`** removes features from the navigation.

## theme.css

Set the variables declared at the top of `web/src/styles.css`:

```css
:root {
  --bg: #12161c;          --surface: #1b222b;   --surface-2: #232c37;  --border: #2f3a47;
  --text: #d7dde5;        --muted: #8994a3;     --accent: #e0a43a;     --accent-ink: #1a1306;
  --accent-soft: rgba(224, 164, 58, .16);
  --good: #5fb878;        --bad: #e2604a;       --warn: #e0a43a;       --focus: #7cb7ff;
  --slot: #202833;        --slot-hover: #28323f;
  --radius: 4px;          --radius-small: 3px;  --shadow: none;
  --font-body: system-ui, sans-serif;           --font-display: Georgia, serif;
  --topbar-bg: #0e1217;   --nav-bg: #161b22;
  color-scheme: dark;
}
```

Any other CSS is allowed too. The class names follow the component they style: `.slot`, `.panel`, `.resbar`, `.nav__link` and so on.
