# Content packs

A content pack is a folder under `content/` with a `pack.yaml`. It defines the whole ruleset. Choose the pack with `OVIAN_PACK` (Docker) or `OVIAN_CONTENT_DIR` (server).

The engine validates the pack at startup and lists every problem it finds: unknown resources, missing buildings, bad references and so on. The Rust tests also validate every shipped pack.

## Curves

Many values depend on a building level. A curve is either a table or a formula:

```yaml
curve: [0.03, 0.06, 0.09]                    # level 1, 2, 3 (higher levels reuse the last value)
curve: { base: 8, factor: 1.35, round: 1 }   # base * factor^(level-1), rounded to a multiple of 1
```

Level 0, meaning not built, is always 0.

## Top level

| Key | Meaning |
|---|---|
| `id`, `name`, `version`, `description` | Identity, shown to players. Ids are `lower_snake_case`. |
| `world` | `speed`, `width`, `height`, `seed`, `generator` (`grid` or `islands`). |
| `resources` | List of `{id, name, upkeep}`. At most one resource has `upkeep: true`; troops and population consume it. |
| `village` | Founding rules, see below. |
| `buildings`, `units`, `tribes` | See below. |
| `combat` | `base_defense` (flat defense of every village) and `loss_exponent` (1.5 is classic). |
| `extensions` | Free-form data for server plugins. The engine ignores it. |

Unknown keys are ignored, so a pack can carry data for plugins anywhere.

## Village

```yaml
village:
  base_production: { wood: 6, grain: 12 }   # per hour, before any building
  base_storage: 800                         # capacity when no storage building covers a resource
  field_slots: [woodcutter, woodcutter, farm]   # one entry per resource slot, fixed building type
  center_slots: 20                          # free building sites
  build_queue: 2                            # parallel construction jobs (phases can raise it)
  start:
    resources: { wood: 750, grain: 750 }
    buildings: [{ building: town_hall, level: 1 }]   # placed in the first center slots
```

### Growth phases

A city can grow like the village, town and city ages of real-time strategy games: center sites open as one building rises.

```yaml
village:
  center_slots: 20
  growth:
    building: town_hall          # a center building
    phases:                      # ascending; the first applies from the start
      - { id: village, name: Village, level: 1,  center_slots: 8 }
      - { id: town,    name: Town,    level: 5,  center_slots: 14 }
      - { id: city,    name: City,    level: 10, center_slots: 20, build_queue: 3 }
      - { id: metropolis, name: Metropolis, level: 20, center_slots: 20, build_queue: 4 }
    extra_sites: { from: 20, every: 5, sites: 3 }   # optional: 3 more sites at level 20, 25, 30 ...
    extra_fields: { every: 10, fields: [woodcutter, clay_pit, iron_mine, farm] }   # optional
```

- `extra_fields` opens one more production field of each kind in `fields` every `every` levels: four at level 10, eight at 20, up to 24 at level 60. These sites come after the center sites in `state.slots` (from index `len(field_slots) + center_slots`), in rounds of `fields`, and hold only that field. The economy reports how many are open as `extra_fields`; the rest are locked (`site_locked`).

- `extra_sites` keeps opening sites after the last phase's count: `sites` more at level `from`, and again every `every` levels. The total never exceeds `village.center_slots`. The shipped packs reach 47 sites at level 60.

- A phase's optional `build_queue` sets how many construction jobs run at once. Without it, `village.build_queue` applies.
- Jobs on different sites run in parallel. Another level of a site already under construction waits for the previous one.
- Technologies with `build_queue: n` add more parallel jobs.
- If a pack changes `center_slots`, existing villages gain or lose empty sites the next time they are loaded.

- Building on an empty site beyond the open count fails with `site_locked`. Buildings that already stand are never affected.
- The village economy reports `center_sites` and `phase` to clients.
- Without `growth`, every site is open.

## Buildings

```yaml
- id: warehouse
  name: Warehouse
  description: Stores wood, clay and iron.
  slot: center          # field (fixed resource slot) or center (free site)
  max_level: 20
  requires: { town_hall: 1 }
  cost: { base: { wood: 130, clay: 160 }, factor: 1.28 }   # level L costs base * factor^(L-1)
  time: { base: 500, factor: 1.3 }                         # seconds at world speed 1
  population: 1                                            # upkeep consumers per level
  unique: false                                            # may stand on several sites (default: true)
  effects:
    storage: { resources: [wood, clay, iron], curve: { base: 1200, factor: 1.28, round: 100 } }
```

| Effect | Meaning |
|---|---|
| `production: {resource, curve}` | Adds hourly production. |
| `storage: {resources, curve}` | Capacity for those resources; the largest building wins. |
| `build_speed: curve` | Multiplier on construction time in the village, e.g. 0.9 is 10% faster. |
| `train_speed: curve` | Multiplier on training time for units trained in this building. |
| `defense: curve` | Fractional defense bonus, e.g. 0.2 is +20%. |
| `hide: curve` | Amount of each resource raiders cannot take. |
| `culture: curve` | Culture points, which radiate to nearby cities. See Culture below. |
| `contentment: curve` | Contentment points for this city only (gardens, baths, games). Together they count up to `contentment.amenities_max` (30). |
| `culture_share: curve` | Share of the city's culture sent to its overlord's city (a cultural exchange); all add up, at most 90%. |
| `garrison: curve` | Overlord troops that may be out on campaign from this city at once (a garrison). |

A building with `foreign: true` stands only in the foreign quarter of a vassal city (see Embassies below).

**Unique and repeatable buildings.** Buildings are unique by default: one per village, like a town hall, a temple or a university. With `unique: false` a center building can be built on several sites, like houses, storehouses or barracks:

- Production, hiding and defense always add up over every building.
- Storage adds up over copies of the same building. Different buildings storing the same resource do not stack: the largest counts.
- Training uses every copy in parallel. Each copy contributes its own rate (1 / training-time multiplier at its level), so two equal barracks train twice as fast.
- Requirements look at the highest level among the copies.
- The growth building must be unique.

## Culture

```yaml
culture: { radius: 12, prestige_max: 0.25, prestige_scale: 0.12 }
```

- **A city's culture** is the sum of its `culture` effects, typically from a Temple and a University.
- **Influence** is full at the city and fades linearly to nothing at `radius` tiles. A player's influence at a place is the sum over their cities.
- **Prestige in battle:**
  - At the battlefield (the defending city), both players' influence is compared.
  - The dominant side gets `prestige_scale × ln((own + 10) / (other + 10))`, capped at `prestige_max`.
  - The attacker receives it as an attack multiplier, the defender as extra defense.
  - Battle reports show it. `GET /villages/{id}/culture` lists every foreign city within reach, with the prestige you would have attacking it and defending against it.

## Demolition

```yaml
extensions:
  demolish: { refund: 0.5, keep: [] }
```

`POST /villages/{id}/sites/{slot}/demolish` pulls down the building on a center site at once. The site is empty again, and `refund` (half by default) of what all its levels cost comes back, into the storage as it stood before (what does not fit is lost).

- **What stays.** Fields, the growth building (civic centre, town hall), great buildings, the wonder and anything listed in `keep` cannot be pulled down.
- **When not.** Not while a construction is queued on that site (`site_busy`), and not the last building of its kind while troops train or research runs in it (`building_in_use`).
- **Afterwards.** The `ovian_build_demolished` hook runs: contentment is recomputed, and a temple's favor is settled and stops growing. The owner gets a `build.demolished` event with the refund.

## Starvation

```yaml
extensions:
  starvation: { tick_hours: 1, share: 0.25 }
```

When a city's stock of the upkeep resource is empty and it still eats more than it produces, its troops starve. Every `tick_hours` (game hours) the lowest-ranking troops (the cheapest) die first, its own and foreign troops stationed there alike, until their upkeep covers `share` of the deficit (at least one soldier). It stops once the city feeds itself. Owners get a `starvation` report; the village view carries `starvation` (`deficit`, `starving`, `empty_at`, `troops`) while the city is short. Leave the key out to switch it off.

## Submission

```yaml
extensions:
  submission: { wins: 5, tribute: 0.1, kinds: [attack, raid],
              benefits: { production: 0.05, defense: 0.15, contentment: 5, trade_speed: 0.5 } }
```

A server module, configured through `extensions`, with defaults as shown.

- **Counting wins.** Every battle of a listed kind that a player wins against a foreign city counts. A successful defence clears that player's count. Each city shows who is beating it (`dominance.threats`) and whom it is beating (`dominance.conquests`).
- **Submission.** On the deciding win (the `wins`-th in a row), the city becomes a vassal of the attacking city, and every count against it starts again.
- **Tribute.**
  - The vassal pays `tribute` (a fraction) of its gross production to its overlord, continuously.
  - The engine handles it through two village-state fields: `tribute` on the vassal and `tribute_in` on the overlord. The economy reports both as `tribute_out` and `tribute_in`.
  - The server keeps the overlord's income equal to the sum of its vassals' payments, also when a vassal's production changes.
- **Culture.**
  - A vassal's culture radiates for its overlord's player, in battle prestige and in `GET /villages/{id}/culture`.
  - Every building keeps the architecture it was founded in (`style` on its slot). Buildings founded while the city is a vassal take the overlord's style, older ones keep theirs, so a city conquered twice shows three styles. The map shows the overlord's emblem.
- **Protection.** In return a vassal (not a colony) gets `benefits`: `production` (more of everything), a `defense` bonus against every attacker except its overlord, `contentment` points, and merchants and reinforcements between it and the overlord's cities travelling `1 + trade_speed` times faster. Leave `benefits` out for these defaults, list only the ones you want, or set `benefits: {}` for none. The village view shows them under `submission.benefits`.
- **Freedom.** A vassal breaks free by winning one battle against its overlord's city. Another player can also beat it into submission, which replaces the overlord. The overlord can release it with `POST /villages/{id}/vassals/{vassal}/release`, except a ver sacrum colony (see below).
- **Visibility.**
  - Battle reports carry a `submission` block with the count, `submitted`, `freed` or `reset`.
  - The map lists `overlord_*` and `vassals` for every city. The rankings count vassals.
  - Events go to both players: `village.submitted`, `village.vassal_gained`, `village.freed` and `village.vassal_lost`.

- **Taxes.** The overlord sets the tribute, from `taxes.min` to `taxes.max`: a default for all its vassals (`POST /me/vassal-tax`) and, if it likes, a rate per city (`POST /villages/{lord}/vassals/{vassal}/tax`; `rate: null` follows the default again). Above the usual tribute, taxes cost `per_point` contentment per percentage point, times `1 + distance / taxes.distance`: far-off cities grow restless first. Lower taxes please the city.
- **Voluntary vassalage.** A free city offers fealty to another player's city (`POST /villages/{id}/fealty` with `to`). That city's owner accepts or declines (`POST /villages/{lord}/fealty/{vassal}/accept|decline`), and the offer can be withdrawn (`DELETE /villages/{id}/fealty`). A voluntary vassal pays `voluntary.tribute`, gets the same protection, and may renounce at any time (`POST /villages/{id}/renounce`).

```yaml
submission: { wins: 5, tribute: 0.1, voluntary: { tribute: 0.05 },
              taxes: { min: 0, max: 0.3, per_point: 1, distance: 15 } }
```

## Embassies

Each new overlord opens a foreign quarter at the end of its vassal's site list:

- **The embassy site** and `overlord_slots` **overlord sites**. Only that overlord builds on them, and it pays from one of its own cities (`POST /villages/{vassal}/foreign/{slot}` with `from` and, for a new building, `building`; `POST /villages/{vassal}/embassy` for the embassy). The owner of the city can never build there, cancel that work, or pull it down.
  - `embassy`: contentment for the vassal (antiquity).
  - `cultural_exchange`: sends 5% of the vassal's culture per level to the overlord's city (`culture_in` on its state).
  - `garrison`: the overlord's troops stationed there may set out from it (`send` with `garrison: <vassal id>`), up to 100 per level out at once. Survivors return to the garrison; loot goes home.
- `exchange_slots` **sites of the city's own** for foreign buildings: the `exchange` lowers the tribute by `exchange_relief` per level.
- **Stewardship** (`steward_level`, antiquity 6): while no governor rules the city (neither its own nor a prefect) and the overlord's embassy stands at that level or higher, the overlord manages the city's construction as if it were their own. They open it (`GET /villages/{vassal}` answers with `steward: true`), and order and cancel buildings there with the usual routes, paid from the city's own stores. Training, research and the rest stay the owner's. `0` turns it off.
- **Breaking free** (or passing to another overlord) leaves every overlord building as `ruin`, in the old overlord's style, and drops unfinished work (the overlord gets its money back). The city may clear ruins, but the sites stay that overlord's. If the same player rules the city again, it gets its old sites back.

```yaml
embassies: { building: embassy, ruin: ruin, exchange: exchange, exchange_slots: 1, exchange_relief: 0.03,
             overlord: [cultural_exchange, garrison], overlord_slots: 2, steward_level: 6 }
```

### Civil servants (militia)

Techs listed in `militia.techs` (antiquity: **Civil Servants**, Fortress 10, after Veterans) make a city's citizens fight when it is attacked or raided: its population times the tech's value, as the people's spearman (`<tribe>_infantry_spearman`, else its cheapest infantry; `units` overrides per tribe). They stand as one more group of defenders, appear in the report under `defender.militia`, and go back to work afterwards: the fallen do not lower the population. The village view lists them as `militia`.

```yaml
militia: { techs: { civil_servants: 1.0 } }
```

### Wikipedia references

`wikipedia` gives an English Wikipedia article for each building and unit (titles; clients link `base` + title, and show
nothing for ids without one). Antiquity covers all of them.

```yaml
wikipedia:
  base: https://en.wikipedia.org/wiki/
  buildings: { civic_centre: Agora, baths: Thermae }
  units: { athen_infantry_spearman: Hoplite, rome_infantry_spearman: Triarii }
```

### Settlers

`settlers.unit` names a unit suffix (antiquity: `settler`, so `<tribe>_settler`, trained in the civic centre from level 10, at three times the cost of a ver sacrum; `roster.extra` in `tools/zeroad/antiquity.yaml` adds it to every people). Send settlers with an attack or a raid on a barbarian camp: if the attackers win and a settler lives, one stays and the camp becomes the attacker's city, a colony of the city it came from (bound like a ver sacrum colony). It starts as a new city does plus all the camp's stores, even beyond its storage; the troops carry no loot home. The battle report has `settled`, and a `ver_sacrum` report announces the colony.

Each settler costs `price_growth` (1.5) times more for every city the player holds beyond the first and for every settler they already have (at home, marching, stationed or in training); the village view's `settler_price` is the current multiple.

```yaml
settlers: { unit: settler, price_growth: 1.5 }
```

Barbarian camps may also yield a find among the spoils: `archaeology.camp_find_chance` × the camp's level, at most `camp_find_max`, named from `archaeology.finds.camp`.

### Auxiliaries

With a garrison in a vassal, the overlord may train the vassal's own units there (`POST /villages/{vassal}/auxiliaries` with `from`, `unit`, `count`): the vassal's civilization, buildings and techs; the overlord pays `cost` times the price. They are stationed in the garrison, count against its room (levied plus in training), and set out from it like the other troops. Every 100 levied cost the city `mood_per_100` contentment for `mood_hours` (at most `mood_max`). When the city breaks free its auxiliaries join its army; levies in training are paid back.

```yaml
auxiliaries: { cost: 1.25, mood_per_100: -3, mood_max: -15, mood_hours: 24 }
```

## Frontier

### The lie of the land

`terrain`: a city quarries more stone next to mountains (and hills) and cuts more wood next to forests. Every tile within `radius` (default 2, a square around the city) adds its `per_tile` bonus: mountain +5% stone, hills +2% stone, forest +5% wood by default, capped by `max` (+40% each). The village view shows it as `terrain {radius, around, bonus}`.

### City spacing

`cities.min_distance` (default 3): no new city (a new player, a ver sacrum colony, a barbarian camp) may be founded closer than this many tiles to another, so the map stays readable.

### Abandoned cities

A player not seen for `abandon.days` real days (not on vacation, not a bot) loses every city to the barbarians: each becomes a camp, "Ruins of <name>", keeping its troops and stores (or a camp garrison when it had none), one camp level per `per_level` population. Vassals go free, foreign garrisons march home, trade routes and offers end. Settlers can found a colony in the ruins. A player who comes back with no city starts afresh with a new one. Without `abandon`, cities are never abandoned.

```yaml
abandon: { days: 7, every_minutes: 60, per_level: 400 }
```

### The barbarian horde

Every `horde.every_hours` real hours the barbarians gather against the player with the largest population (seen within `active_days`, not protected or on vacation). The horde leaves the nearest camp `warning_hours` after the alarm, which the chronicle gives to the whole world so neighbours can send reinforcements. It has `ratio` troops per soldier defending the city (at least `min_troops`). Survivors do not stay: their loot is left in the camp. Battle reports carry `horde: true`; throwing it back counts as `hordes_repelled` for the defender and every player whose troops fought there.

```yaml
horde: { every_hours: 24, warning_hours: 3, ratio: 1.0, min_troops: 150, active_days: 3 }
```

### Trade profit and bandits

Merchants' journeys leave no reports. With `trade`, merchants who deliver to another player's city bring home `profit_per_tile` of the cargo for every tile travelled (at most `profit_max`), up to `profit_cap_per_level` a day per market level. Beyond `bandits_from` tiles and off the roads, bandits may rob a caravan (`bandits_per_tile` per tile beyond, at most `bandits_max`) and take `bandits_take` of it; a robbed caravan earns nothing. A robbery of a one-off shipment is reported; a route shows it on the route. The village view's `market.trade` has the rules and `profit_today` / `profit_cap`.

```yaml
trade: { profit_per_tile: 0.01, profit_max: 0.25, profit_cap_per_level: 2000, bandits_from: 6, bandits_per_tile: 0.02, bandits_max: 0.3, bandits_take: 0.5 }
```

### Treaties

Players swear pacts of peace (`POST /treaties` with `to` and an optional `tribute`: `payer` "me" or "them", `resources`, `every_hours`; the other side accepts with `POST /treaties/{id}/accept`; `DELETE /treaties/{id}` withdraws, declines, or gives `notice_hours` of notice). The tribute goes from the payer's first city to the other's first city; unpaid, the pact lapses. A pact does not stop an attack: attacking or raiding a partner breaks it, marks the breaker `treacherous` on the map and in profiles for `treachery_hours`, and costs their cities `treachery_mood` contentment meanwhile.

```yaml
treaties: { notice_hours: 6, treachery_hours: 48, treachery_mood: -15, min_tribute_hours: 1 }
```

## Archaeology

Every town and foreign site keeps its **layers**: a building pulled down, or an overlord's building fallen to ruin, is remembered with its building, style, level, founder, dates and end. Under them, `ancient_chance` of the sites hide a prehistoric settlement (one of `ancient`, fixed per city, site and world).

- `POST /villages/{id}/sites/{slot}/excavate` digs an empty site or a ruin (a current overlord's sites excepted), for `cost`, in `hours` (at world speed). It uncovers the top undug layer, or probes for the ancient one; a site found empty is dug to the rock and cannot be dug again. Digging a ruin clears it. `DELETE` on the same path calls the diggers off.
- Each layer gives one **find**, graded by `grades` (chance, culture), named from `finds[building]` (`default` otherwise) or the ancient people's list. It is kept in the city; the best `display.per_level` × levels of the `display.building` are shown and add their culture (`culture_relics` on the state). `POST /finds/{id}/move` moves one to another own city.
- Finds outlive their finders and cities. `GET /finds` (public, `before` and `limit` to page) and `GET /finds/{id}` give records in the `ovian-find/1` format: `uri` (`ovian://<world>/finds/<id>`), name, grade, culture, finder, owner, where it is kept, and `context`: world, pack, site (city, coordinates, slot), depth and the layer (building and its name, style and civilization name, level, founded and ended, founder, how it ended; or the ancient people and age). Other games can import them, e.g. into a museum.

```yaml
archaeology:
  cost: { food: 400, wood: 300, stone: 200, metal: 100 }
  hours: 2
  ancient_chance: 0.4
  display: { building: temple, per_level: 1 }
  grades: { common: { chance: 0.65, culture: 1 }, fine: { chance: 0.28, culture: 3 }, exceptional: { chance: 0.07, culture: 8 } }
  ancient: [ { id: bronze, name: Bronze Age settlement, age: c. 1600 BC, finds: [bronze dagger, stirrup jar] } ]
  finds: { embassy: [envoy's seal, inscribed treaty stele], default: [potsherds, oil lamp] }
```

## Governors

Players hire governors from `candidates` people of their civilization (names from `names[tribe]`, else `names.default`), each with two `traits`; the offer changes every `refresh_hours`. The next one costs `hire` × (1 + governors in service); at most one per city held or ruled. `GET /me/governors`, `POST /me/governors` (`candidate`, `from`), `POST /governors/{id}/appoint` (`village_id`), `/recall`, `DELETE /governors/{id}`.

A governor travels at `speed` tiles/hour, then rules the city. Traits give `contentment` points; multiply unrest growth (`unrest`), calming (`calm`), crowding (`size`), tribute anger (`tribute`) and agitators (`agitators`); add `production` (all resources) and `defense`. In a vassal, the overlord's governor is a **prefect**: it sends the city's own governor back to court, the people take `prefect` contentment, and the vassal appoints nobody while it rules. A vassal that breaks free sends the prefect home; one that rises up kills them.

```yaml
governors:
  hire: { food: 1500, wood: 1500, stone: 1000, metal: 2000 }
  candidates: 3
  refresh_hours: 24
  speed: 8
  prefect: -3
  traits: { just: { name: Just, text: "...", contentment: 4 }, harsh: { name: Harsh, unrest: 0.6, contentment: -3 } }
  names: { rome: [Gaius Flaminius, Quintus Fabius], default: [Aulus, Kallias] }
```

## Ver sacrum

```yaml
extensions:
  ver_sacrum: { every: 10, range_per_level: 0.5, speed: 6, tribute: 0.1, cost: { food: 8000, wood: 6000, stone: 4000, metal: 3000 } }
```

A server module, named after the Italic "sacred spring", when a people sent its young away to found a new settlement.

- **Earning one.** Every `every` levels of the growth building (civic centre, town hall) earn a city one ver sacrum. A level 20 civic centre has earned two.
- **Range.** The colony goes on a free, settleable tile at most `level × range_per_level` tiles away: half the level, so 10 tiles at level 20.
- **The journey.**
  - `POST /villages/{id}/ver-sacrum {x, y, name}` pays `cost` and sends the migrants.
  - They travel at `speed` tiles per hour, at world speed.
  - If someone settles the tile first, the migrants come home, and the cost and the ver sacrum are refunded.
- **The colony.**
  - It belongs to the same player, who manages it like any other city.
  - It is also a vassal of its mother city: it pays `tribute` of its production, and its culture follows the mother (see Submission).
  - It can never be released: the release call fails with `colony_bound`, and the clients mark it as a colony instead of offering Release. Vassal lists carry `colony: true` for it.
- **The village view** has a `ver_sacrum` block: earned, used, available, range, cost, migrations under way and colonies founded.

## Technologies

```yaml
techs:                      # prerequisites must be listed before the techs that need them
  - id: metallurgy
    name: Metallurgy
    building: university    # where it is researched
    level: 3                # the level that building needs
    after: [philosophy]     # techs needed first
    requires: { stable: 1 } # other buildings needed (optional)
    cost: { wood: 600, iron: 900 }
    time: 7200              # seconds at world speed 1
    build_queue: 0          # extra parallel construction jobs (optional)
    field_levels: 0         # extra levels for production sites in this city (optional; antiquity: Industry, +5)
```

- **Research** happens once per village, one tech at a time, through `POST /villages/{id}/research`. Cancelling refunds the cost.
- **Units** list the techs they need in `techs: [metallurgy]`. Training without them fails with `tech_missing`.

## Units and tribes

```yaml
tribes:
  - { id: legion, name: Legion, description: Disciplined and balanced. }
units:
  - id: legionary
    tribe: legion
    building: barracks          # where it is trained
    requires: { barracks: 3 }
    class: infantry             # infantry or cavalry: defenders have a value against each
    cost: { wood: 120, clay: 100, iron: 150, grain: 30 }
    upkeep: 1                   # per hour, in the upkeep resource
    time: 900                   # seconds per unit at world speed 1
    attack: 40
    defense: { infantry: 35, cavalry: 50 }
    speed: 6                    # tiles per hour
    carry: 50                   # loot capacity
```

## Battle model

The attack is split into infantry and cavalry shares. Defense is each defender's infantry and cavalry value, weighted by those shares, plus `base_defense`, times `1 + wall bonus`. With `x = (weaker / stronger) ^ loss_exponent`:

- **attack**: the loser is wiped out, and the winner loses a fraction `x`.
- **raid**: the winner loses `x / (1 + x)` and the loser loses `1 / (1 + x)`.

Survivors carry loot home up to their carry capacity, spread evenly across resources, minus the hidden amount.

## Making a new pack

1. Copy `content/classic` to `content/<yourpack>`.
2. Edit `pack.yaml`.
3. Run the Rust tests or start the server. Both list every validation problem.
4. Optionally make a skin with matching icons and vocabulary. See [skins.md](skins.md).
