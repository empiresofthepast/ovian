# Society: alliances, trade, heroes, camps, quests, gods, great buildings and the wonder

Each feature is a server module under `server/src/ovian_server/modules/`. Each is configured in the pack's `extensions` block; the shipped settings are in `content/classic/pack.yaml` and `tools/zeroad/antiquity.yaml`. The diorama has a screen for each of them; the ledger shows alliance tags and the battle effects, and its other screens are still to come.

| Feature | Module | Screen in the diorama |
|---|---|---|
| Alliances, diplomacy, chat, shared reports | `alliances.py` | Alliance (L) |
| Merchants and market offers | `market.py` | Market (T), and the market building |
| Scouting and the battle simulator | `scouting.py` | Rally point (R): Scout, Battle simulator |
| Heroes | `heroes.py` | Hero (H); the Rally point offers "leads the army" |
| Barbarian camps and quests | `pve.py` | Map (the ⚔ camps), Quests (Q) |
| Gods: favor and powers | `gods.py` | The temple's panel |
| Great buildings | `great.py` | The building's panel, and the map for other players' |
| Vacation, night, ranks, achievements, wonder | `player_rules.py` | Settings, Quests, Rankings → Wonder race |

## Alliances

- **Roles.**
  - The leader can do everything, including promoting members and handing over the lead.
  - Officers invite, remove members and set diplomacy.
  - Members chat and see the shared reports.
- **Diplomacy** between alliances:
  - An alliance (`ally`) or a non-aggression pact (`nap`) is in force once both sides have proposed the same thing.
  - `war` is declared by one side alone, and `none` ends any relation.
  - Members, allies and pact partners cannot attack, raid or scout each other, nor call divine wrath on each other.
- **Chat.** Alliance chat is delivered as `alliance.message` events on each member's private topic, so outsiders cannot listen in.
- **Shared reports.** `GET /alliance/reports` returns the members' recent battle and scouting reports.
- **Where tags show.** The map and the player rankings show alliance tags. `GET /alliances` ranks the alliances.

## Market

```yaml
market: { building: market, carry: 1000, speed: 12 }
```

- A city has one merchant per level of its market, each carrying `carry` and travelling `speed` tiles per hour.
- **Shipments.** `POST /villages/{id}/market/send` ships resources to any city. Merchants come back after delivering.
- **Offers.** An offer (`POST /villages/{id}/market/offers`) holds its goods and merchants until someone accepts it (`POST /market/offers/{id}/accept`) or it is withdrawn. On acceptance, both caravans set out.

## Scouting and the simulator

```yaml
scouting: { stealth: 10 }
```

- Send any troops with `kind: scout`. They get through when they number at least a tenth of the defenders, home troops and reinforcements together.
- **If they get through,** the report shows stores, troops, reinforcements, buildings, defense bonus and whether the hero is home. The defender learns that scouts slipped past.
- **If they don't,** they die.
- **The simulator.** `POST /simulate` runs the battle engine on any two armies. The diorama's Battle simulator runs the same engine in the browser, through WebAssembly.

## Heroes

```yaml
heroes: { xp_base: 100, attack_per_point: 0.03, defense_per_point: 0.03, production_per_point: 0.02, revive: 14400, speed: 10 }
```

- **Choosing one.** Each player chooses one hero from their civilization's 0 A.D. heroes, such as Pericles, Themistocles or Xenophon for the Athenians. Packs without 0 A.D. data offer generic heroes.
- **Experience.** It is the value of the enemy troops killed, divided by 100, and doubled against barbarian camps. Level L needs `xp_base × L(L+1)/2`, and each level gives a point.
- **Skills:**
  - Command: attack bonus for the army the hero leads.
  - Guard: defense bonus in the home city.
  - Stewardship: production bonus in the home city, applied through the engine's `boost`.
- **Death and travel.** A hero whose whole army falls dies and returns after `revive` seconds, at world speed. Heroes travel between your cities at `speed`.

## Barbarian camps and quests

```yaml
camps: { count: 12, min_distance: 4, max_distance: 16, max_level: 5, troops_per_level: 12, regen: 3600, loot_per_level: 1500 }
```

- **Camps:**
  - They belong to the non-player "Barbarians" account.
  - There are `count` of them plus one per five players, placed around the players' cities.
  - A camp of level L holds `troops_per_level × L` warriors of a random civilization and `loot_per_level × L` of each resource.
  - It recovers `regen` seconds after a battle.
  - Camps can't be submitted, aren't ranked, and give heroes double experience.
- **Quests** (`extensions.quests`) form a chain with goals and rewards:
  - The goals are a building level, troops at home, a counter (battles won, camps beaten, caravans, great-building points), culture, cities, vassals, an alliance, or a hero level.
  - Three are shown at a time, and rewards go to the city you are looking at.

## Gods

- **Favor.** Each city's temple gathers favor: `favor_per_level × level` per hour at world speed, up to `max_favor`.
- **Powers,** in the shipped packs:
  - Blessing: +25% production for 2 hours.
  - Divine shield: +30% defense for 2 hours.
  - Battle fury: +20% attack for the next army to fight.
  - Wrath: a foreign city within 20 tiles loses 15% of its stores. It can't strike protected, vacationing or friendly players.

## Great buildings

```yaml
great_buildings: { buildings: [great_theatre, great_forge], reward: 0.5 }
```

- **Building them.** The owner builds them like any building. Anyone can also contribute resources towards the next level, and when contributions reach its cost the level is finished at once.
- **Rewards.** Contributors from other players get half their contribution back when the level is finished, in their first city.
- **Finding them.** `GET /great-buildings?x=&y=` lists those nearby.

## Vacation, night, ranks and achievements

- **Vacation.** `POST /me/vacation {hours}` lasts from 12 hours to 14 days.
  - While it lasts, nobody can attack, raid, scout or curse your cities.
  - You can't give orders yourself, and production goes on.
  - The map shows such players as protected.
- **Night** (`night: { start: 0, end: 6, defense: 0.25 }`): battles fought between those hours, server time (UTC), give the defender extra defense. It is in the antiquity pack.
- **Ranks.** In antiquity, Drill (barracks 5) and Veterans (fortress 3, after Drill) each add 10% to the attack and defense of the city's troops.
- **Achievements** are unlocked from counters and city state and listed at `GET /achievements`.

## The wonder

```yaml
wonder: { building: wonder }
```

- **The race.** The first player to finish the wonder's last level (25) wins the world. The win is announced on the server topic as `world.won`, and `GET /world/victory` shows the winner and the race. The game goes on afterwards.
- **Requirements.** The wonder needs city centre 20, temple 10 and university 10. In antiquity it uses each civilization's 0 A.D. wonder.

## Ships

Ships are left for later, as a harbour that can only stand beside water. Only coastal cities would have one.
