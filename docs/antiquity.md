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

## Art mapping

The pack's `extensions.zeroad` block records, for every civ, the 0 A.D. template, actor, icon and local name behind each building and unit. For example, Roman barracks are `structures/romans/barracks.xml` and are called *Castrum*. The [diorama front end](diorama.md) uses it to dress each player's city in their civilization's architecture.
