# The realm: people, governments, seasons, omens, roads, espionage, medals, the chronicle and rounds

Each feature is a server module under `server/src/ovian_server/modules/`, configured by
`extensions` in the content pack, and switched off when its key is missing. Every module's
docstring has the full details. The antiquity pack enables all of them; the classic pack leaves out
contentment, governments and seasons (the ones that change production).

| Feature | Module | Pack key | API |
| --- | --- | --- | --- |
| Contentment and unrest | `contentment.py` | `contentment` | village view `contentment` |
| Governments | `governments.py` | `governments` | `GET/POST /me/government` |
| Seasons and the festival | `calendar.py` | `seasons`, `festival` | `GET /calendar`, `POST /festival/{contest}` |
| Omens | `omens.py` | `omens` | village view `omen`, `POST /villages/{id}/omen/{choice}` |
| Roads and trade routes | `roads.py` | `roads`, `trade_routes` | `POST /villages/{id}/roads`, `GET /roads`, `POST /villages/{id}/routes` |
| Espionage | `scouting.py` | `scouting.missions` | `POST /villages/{id}/send` with `kind: scout, mission` |
| Weekly medals | `medals.py` | `medals` | `GET /medals`, `GET /players/{id}/medals`, `GET /hall-of-fame` |
| Starvation | `starvation.py` | `starvation` | village view `starvation`, `starvation` reports |
| Chronicle | `chronicle.py` | `chronicle` | `GET /chronicle`, `GET /chronicle.geojson` (public) |
| Rounds and bans | `rounds.py` | (admin) | `POST /admin/world/new-round`, `POST /admin/players/{id}/ban` |
| Tutorial | `pve.py` | quest `hint` and `focus` | `GET /quests` (`tutorial`), `POST /me/tutorial` |
| AI rulers | `bots/` | `OVIAN_BOT_USERS` | see [bots.md](bots.md) |

## How it fits together

- **Production modifiers.** The engine applies `boost` (all resources) and `boost_by` (per resource),
  both of which may be negative; no resource drops below 10% of its production. `repo.refresh_boost` sums the
  `ovian_boost` hook (contentment, omens, blessings, heroes) and the new `ovian_production` hook
  (seasons, governments). Modules call it, or `repo.refresh_all`, when their inputs change.
- **Contentment** adds up reasons from the city itself, its timed effects and the
  `ovian_contentment` hook (governments, seasons). A happy city produces up to 10% more, and an angry one
  up to 40% less. An unhappy vassal gathers unrest and, at the top, rises up (`release(reason="uprising")`).
  Agitators (the `incite` mission) add unrest directly. Colonies never rebel.
- **Amenities and politics.** Buildings with a `contentment` effect (antiquity: Public Gardens, Public Baths,
  Amphitheatre) add points, up to `amenities_max`. Techs listed in `contentment.techs` change a city's politics once
  researched there (antiquity, at the university: Political Thought, Rhetoric, Codified Law, Citizenship): they add
  points and multiply unrest growth (`unrest`), calming (`calm`), the crowding penalty (`size`), tribute anger
  (`tribute`) and agitators (`agitators`), and `rebel_below` moves the restless line. The view shows them in `contentment.politics`.
- **Travel time** is multiplied by the `ovian_travel` hook: roads (between their two ends), seasons
  (a slow winter) and governments (merchant or marching speed). Armies, scouts and merchants all use it.
- **Timed effects** (omens, festival glory) live in `meta.effects` of a city or a player. An `effect.end`
  job re-applies production when one runs out.
- **The chronicle** is written by the other modules: foundings, colonies, submissions, rebellions,
  big battles, wars and pacts, phases, wonders and great buildings, festival winners, governments and
  rounds. Its GeoJSON places the grid on made-up coordinates (`fictional: true`) unless the pack
  sets `chronicle.geo.real` for a world laid on real ground.
- **A new round** archives the round in the hall of fame and clears the world, then gives every player
  who is not banned a fresh city. Accounts, alliances, achievements, medals, the chronicle and chat stay. A world speed
  chosen there is kept in `world_state` and wins over `OVIAN_WORLD_SPEED`.

Hours in these settings are game hours: they are divided by the world speed.
