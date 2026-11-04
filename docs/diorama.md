# The diorama front end

A second web client, in `web/projects/diorama`. It shows your city in 3D with the art of [0 A.D.](https://play0ad.com) and plays like a real-time strategy game:

- Click a building or an empty site to select it.
- The bottom panel shows the portrait, the stats, and the upgrade, build and train commands.
- Drag to pan. Right-drag or Q/E turns the camera, and the wheel zooms.

It talks to the same API and MQTT broker as the ledger client (`web/src`) and shares its core code (`web/src/app/core`, imported as `@core/*`). Players can use either client on the same world.

| | |
|---|---|
| Port | 47174 (`OVIAN_DIORAMA_PORT`) |
| Packs | All. Each tribe is dressed as a 0 A.D. civilization: `antiquity` maps its civs one to one, `classic` uses Romans, Gauls and Persians, `isles` uses Athenians. |
| Rendering | three.js 0.170, COLLADA meshes, loaded lazily with the village screen |

## The art

The art is not in git. It is baked from a pinned 0 A.D. commit:

```sh
tools/zeroad/bake.sh               # writes web/projects/diorama/public/art/ (about 175 MB, 30 MB gzipped meshes)
docker compose up -d --build diorama
```

The first run checks out the 0 A.D. art (about 4.5 GB) into the `ovian-0ad` Docker volume. Later runs reuse it.

[`tools/zeroad/diorama.yaml`](../tools/zeroad/diorama.yaml) controls the bake:

- **0 A.D. structures** baked per civ: civil centre, storehouse, farmstead, house, barracks, stable, fortress, wall tower, field.
- **Packs:** for each pack, the civ that dresses each tribe and the structure that stands for each building.
- **Gaia art** for resource fields: trees, stone and metal mines, barley.
- **Terrain textures and HUD icons.**

[`bake.py`](../tools/zeroad/bake.py) resolves each actor with its variants, props, textures and materials into `manifest.json`:

- **Meshes** are copied with their image libraries stripped, plus a `.gz` copy that nginx serves directly.
- **Textures** become WebP files of at most 1024 px.
- **Portraits** become 128 px WebP files.

**License.** 0 A.D. art is CC BY-SA 3.0, and the baked files are shared under the same licence. The bake writes `art/ATTRIBUTION.txt`, and the welcome screen credits Wildfire Games.

## How the village is drawn

- **Layout.** The civic centre stands in the middle. The other centre sites sit on rings around it, and resource fields form an outer ring grouped by kind, with grain fields facing the camera.
- **Locked sites** in the current growth phase are not drawn. The town's ground spreads ring by ring as phases open.
- **Buildings** use the player's civ actor. A new building shows the 0 A.D. foundation scaffolding until it is finished.
- **Materials** follow 0 A.D.: the player colour shows where a texture's alpha marks it (`player_trans`), and foliage is alpha-tested.
- **Fields** grow with their level:
  - Woodlines get more trees.
  - Quarries and mines get bigger rock faces and more spoil.
  - Grain fields get more rows of barley.
- **The Wall** raises a ring of wall towers around the town. The ring gets more towers as the wall's level rises.

## Developing

```sh
docker run --rm -v "$PWD/web:/web" -v ovian_web-node-modules:/web/node_modules -w /web node:22-bookworm-slim npx ng build diorama
scripts/e2e_diorama.py         # Playwright walkthrough (see the file header)
scripts/showcase_diorama.py    # dev only: grows test cities in the DB and screenshots them
```

In the browser console, `ovianScene.inspect(siteIndex)` describes what a site rendered.

## Screens

The 3D city is the shell. The other screens open over it as routes, and the scene stays loaded:

| Screen | Key | What it does |
|---|---|---|
| City | C | The 3D city, with the selection panel for building and training |
| Map | M | The world map, painted with 0 A.D. ground textures. Cities appear as civ emblems: gold rings are yours, red rings are others. Select a city to attack, raid or reinforce it. The 3D scene pauses while the map is open. |
| Rally point | R | Pick troops by portrait, choose a target and a mission, and see travel time and loot capacity. Lists incoming and outgoing marches and reinforcements, with recall and send back. |
| Reports | P | Battle reports with unit portraits and losses |
| Rankings | K | Players with their civ emblems; your row is highlighted |
| Settings | O | Quality, shadows, level badges and forest (kept per browser); world and account info; a link to the ledger; leave the game |

Esc closes a screen.

**Not drawn yet:** units walking around the town, armies marching on the map, and chat. Chat is in the ledger client.
