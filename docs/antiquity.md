# The antiquity pack: 0 A.D. rules in Ovian

`content/antiquity` holds fifteen civilizations from [0 A.D.](https://play0ad.com):

- Athenians, Spartans, Macedonians, Ptolemies, Seleucids
- Romans, Carthaginians, Iberians, Gauls, Britons, Germans
- Achaemenids, Mauryas, Kushites, Han

Their unit rosters and stats are converted from 0 A.D.'s simulation data, so nobody types them in by hand.

```sh
tools/zeroad/convert.sh          # fetch 0 A.D. (sparse, cached in the ovian-0ad volume) and regenerate
```

The converter reads [`tools/zeroad/antiquity.yaml`](../tools/zeroad/antiquity.yaml): which civs to include, the scaling factors, the buildings and the village rules. It writes `content/antiquity/pack.yaml`. The 0 A.D. commit is pinned in that config, so the output is reproducible, and CI checks it.

**License.** 0 A.D. simulation data is GPL-2.0-or-later, so the generated pack is GPL-2.0-or-later too. See `content/antiquity/LICENSE`. The rest of Ovian stays MIT.

## What is taken from 0 A.D.

| 0 A.D. | Ovian |
|---|---|
| Civilization (`special/players/<civ>`): name, history | Tribe: name, description (first sentences) |
| Every soldier any structure of the civ can train | Units, after the filters below |
| `Cost/Resources` food, wood, stone, metal | `cost` × `scale.cost` (3.5) |
| `Cost/BuildTime` | `time` × `scale.time` (75 s) |
| `UnitMotion/WalkSpeed` | `speed` × `scale.speed` (0.65 tiles per hour per m/s) |
| `ResourceGatherer/Capacities` | `carry` × `scale.carry` (5); units that cannot gather get 40 (infantry) or 80 (cavalry) |
| Classes Cavalry, Elephant, Chariot | `class: cavalry`; everything else is infantry |
| Champion, cavalry, elephant | Extra upkeep (`scale.upkeep`) |
| Damage, repeat time, range, armour, health, bonuses | `attack` and `defense`, see below |

**Rosters.** Heroes, healers, siege engines, ships and support units are skipped, as are advanced and elite ranks (`_a`, `_e`). Each civ keeps up to 5 citizen infantry, 3 cavalry and 2 champions, the strongest first. The cheapest unit of each kind is available at once. The others need higher levels of the building that trains them, as set in `roster.tiers`:

- Infantry train in the Barracks.
- Cavalry, chariots and elephants train in the Stable.
- Champions train in the Fortress.

**Attack and defense.** 0 A.D. fights unit against unit in real time. Ovian adds attack points against defense points, Travian-style. The converter folds damage and durability into one number, their geometric mean:

```
power = sqrt(effective damage per second × effective hit points)
```

A unit that hits twice as hard and one that lasts twice as long come out equal, as in a Lanchester fight. The inputs:

- **Damage** is Hack + Pierce + Crush, each reduced by the opponent's armour (0.9 per armour level) and divided by the repeat time.
- **Bonus multipliers** apply when they target the opposing class, for example spearmen ×3 against cavalry.
- **Ranged units** get +1% per metre of range, up to 80 m.
- **Hit points** are scaled by the unit's own armour against the average damage mix of the attacking side.

From this:

- `attack` is power against an average mixed army.
- `defense.infantry` and `defense.cavalry` are power against average infantry and average cavalry.

Then two adjustments:

- **Roles** (`scale.roles`) use the 0 A.D. classes to tell attackers from defenders. Ranged units and pikes are better at defense; swords, axes and maces are better at attack.
- **Scale:** everything is multiplied so that the median basic infantryman attacks at 40.

The Rust tests check that the result still plays like 0 A.D.: Roman spearmen hold off a cavalry charge that Roman swordsmen lose.

**Buildings** are Ovian's levelled buildings with 0 A.D. names. Their cost mix (wood, stone, metal) is the average over all civs of the matching 0 A.D. structure, scaled to a fixed total. The Fortress is new to Ovian and trains the champions.

**Phases.** As in 0 A.D., a city moves through the Village, Town and City phases as its Civic Centre grows, and Ovian continues with Metropolis, Capital and Imperial. Early phases open building sites. From the City on, each phase adds a builder: a construction job that runs at the same time as the others.

| Civic Centre level | 1 | 5 | 10 | 20 | 25 | 30 | 40 | 60 |
|---|---|---|---|---|---|---|---|---|
| Phase | Village | Town | City | Metropolis | Metropolis | Metropolis | Capital | Imperial |
| Building sites | 8 | 14 | 20 | 23 | 26 | 29 | 35 | 47 |
| Builders | 2 | 2 | 3 | 4 | 4 | 4 | 5 | 6 |

From level 20, every 5 levels open 3 more building sites.

The University's Architecture adds one more builder. The Civic Centre goes to level 60, with gentler cost and time curves (×1.15 and ×1.2 per level) so the late levels stay reachable. See `village.growth` in [content-packs.md](content-packs.md).

**Temple and University** are unique buildings. Both give culture, which radiates to cities within 12 tiles and gives the culturally dominant side up to +25% in battle. Their 0 A.D. art is each civ's temple. The University uses the civ's library, gymnasium or, failing those, market.

**Tech tree.** Researched once per city:

| Tech | Where | Needs | Unlocks |
|---|---|---|---|
| Philosophy | University 1 | | |
| Architecture | University 5 | Philosophy | one more builder (parallel construction job) |
| Sacred Rites | Temple 1 | | |
| Metallurgy | University 3 | Philosophy | advanced infantry (3rd to 5th in the Barracks) |
| Horse Breeding | University 5 | Philosophy, a Stable | advanced cavalry (2nd and 3rd in the Stable) |
| Hero Cult | Temple 5 | Sacred Rites | champion infantry |
| Strategy | University 10 | Metallurgy, Horse Breeding, Hero Cult | champion cavalry, chariots and war elephants |

The tech icons are 0 A.D. technology portraits.

**Ver sacrum.** Every 10 levels of the Civic Centre earn one ver sacrum: the city's young leave to found a colony at most half the Civic Centre level away, in tiles. The colony is yours to manage, and it pays its mother city 10% tribute for good: it can never be released. See [content-packs.md](content-packs.md#ver-sacrum).

**Submission.** Win five battles in a row against a city and it becomes your vassal. It pays you 10% of its production, its culture radiates for you, and its buildings take on your civilization's architecture. In return it is under your protection: +5% production, +15% defense against anyone but you, +5 contentment, and merchants and reinforcements between it and your cities travel 50% faster. A single win against its overlord sets it free. See [content-packs.md](content-packs.md#submission).

## Economy

The numbers are written for speed 1; the server scales what must grow with the speed when it loads the pack (see below). The rebalance of 2026-11-06 follows these rules:

- **A field pays for itself in weeks, at every level.** Output grows ×1.35 per level and cost ×1.5 (was ×1.67), so a level pays back in about 6 days at level 2 and 13 at level 10 (was 34). All ten levels of one field cost 28k (was 63k).
- **A store fits the costs around it.** A storehouse level holds 1,500 × 1.3^(L−1): 15,900 at level 10, 219,300 at level 20, for about a third of that in cost. No ordinary building wants more than one store a couple of levels ahead of it; the fortress, the dearest, needs a store two levels above its own. The base store is 1,000, enough for any first level a new city can build. Stores are repeatable.
- **Stores grow with the speed.** Capacity, base storage and what houses hide are multiplied by speed^0.5 (`village.storage_speed_exponent`): ×7 at speed 50, where a full set of fields would otherwise fill a speed-1 store in half an hour.
- **Every resource is wanted.** The 0 A.D. cost mixes made wood half of everything a city spends. Fields, stores, houses, barracks, stables, the temple and the wall now take stone and metal too: a whole city to level 10 costs about 38% wood, 38% stone, 13% metal and 11% food, and metal goes mostly to armies and research.
- **World projects scale with the speed.** The great buildings and the wonder are funded by contributions (see [society.md](society.md#great-buildings)); their cost grows ×1.25 (great buildings) and ×1.15 (wonder) per level and is multiplied by speed^0.5 (`cost.speed_exponent`), ×7 at speed 50. In round 1 of the live world the wonder went up 24 levels in one afternoon at speed 50; at that speed its 25 levels now cost about 300M, a week of a six-city empire at full stretch, and a funded level still takes its construction time.
- **Time curves stay playable at speed 1.** The Civic Centre's build time grows ×1.14 per level (was ×1.2), so level 60 takes about two days with its own bonus instead of a month; fields ×1.5 (was ×1.6).

| Building | Levels | Level 1 | Level 10 | Top level | Per level |
|---|---|---|---|---|---|
| Woodline, Quarry, Mine, Field | 10 | 250–270 | 9,600–10,400 | 9,600–10,400 | ×1.5 |
| Storehouse (holds 1,500 → 15,900 → 219,300) | 20 | 500 | 5,300 | 73,100 | ×1.3 |
| Farmstead (same capacity) | 20 | 350 | 3,700 | 51,200 | ×1.3 |
| Civic Centre | 60 | 185 | 650 | 705,000 | ×1.15 |
| Barracks, Stable | 20 | 720–725 | 6,700 | 78,000–79,000 | ×1.28 |
| Fortress | 20 | 2,400 | 17,900 | 166,500 | ×1.25 |
| Temple, University | 20 | 900–1,100 | 8,300–10,100 | 98,000–120,000 | ×1.28 |
| Great Theatre, Great Forge | 30 | 4,000 | 29,800 | 2.58M | ×1.25, × speed^0.5 |
| Wonder | 25 | 200,000 | 704,000 | 5.73M | ×1.15, × speed^0.5 |

Totals are the sum over the four resources at speed 1. Run `tools/zeroad/convert.sh` after changing `tools/zeroad/antiquity.yaml`; a spawned world can change any of these without a new pack through its overrides (`buildings`, `village`, see [worlds.md](worlds.md)).

## Art mapping

The pack's `extensions.zeroad` block records, for every civ, the 0 A.D. template, actor, icon and local name behind each building and unit. For example, Roman barracks are `structures/romans/barracks.xml` and are called *Castrum*. The [diorama front end](diorama.md) uses it to dress each player's city in their civilization's architecture.

## Cultural names

Every civilization calls its buildings by its own names, and each name links to the Wikipedia article about that building in that culture (`extensions.cultures` in [`antiquity.yaml`](../tools/zeroad/antiquity.yaml), see [content-packs.md](content-packs.md#cultural-names)). A Roman house is a *Domus* and links to Domus; a Carthaginian one is a *Bet* and links to Kerkouane, the best-preserved Punic town; a Han one is a *Mín Jū*. The university is Athens' *Akadēmeia* (the Platonic Academy), Alexandria's *Mouseion*, the Mauryas' *Takṣaśilā* (Taxila), the Han *Tàixué*, the Druids for the Gauls and Britons, the runes for the Germans. The 0 A.D. names are the starting point where a structure exists (Oikos, Castrum, Nemeton, Huvādā); the buildings 0 A.D. does not have, or that it only approximates with another structure (university, gardens, baths, amphitheatre, embassy, great buildings), get names of their own. All titles are checked against Wikipedia when they are written; the converter checks that every civilization names every building.

The clients show the name of the culture whose architecture a building wears: its slot's style, so a building raised under a former overlord keeps its foreign name, and the pack's generic name stands under it.
