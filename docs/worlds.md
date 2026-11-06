# Many worlds: the hub, founders, badges and Patreon

One Ovian server runs one world: one content pack, one speed, one database. To run several worlds side by side,
and let a player use **one account** for all of them, add the **hub**. Without a hub everything works as before:
each world has its own accounts.

```
                 ┌──────────── browser: one site (empires.ofthepast.org) ────────────┐
                 │  /         3D client      /ledger/   ledger client                │
                 │  /hub/…    hub API        /api/…     main world   /w/w3/…  world w3│
                 └───────┬───────────────────────┬────────────────────────┬─────────┘
                         │                       │                        │
                     ┌───▼───┐  ticket (signed)  ┌▼──────────┐       ┌─────▼─────┐
                     │  hub  │──────────────────▶│ world w2  │       │ world w3  │  each: server + broker + database
                     └───┬───┘◀── who joined ────└───────────┘       └───────────┘
                         │   ── new badges ──▶ (every world the account plays in)
                    accounts, founders, badges, Patreon, the list of worlds
```

1. The player logs into the hub and picks a world from its list.
2. The hub gives the player a **ticket**: a token valid for five minutes, for that one world, signed with a
   secret the hub shares with its worlds (`OVIAN_HUB_WORLD_SECRET`). It carries the account's name, founder
   number and badges.
3. The client hands the ticket to the world (`POST /api/v1/auth/hub`). The world logs in the account's player, or
   founds one on the first visit (the client then asks for a people). From there on the client talks to the world
   exactly as without a hub.

A player who already lived in a world before the hub keeps their cities, and simply logs into the hub with that
world's name and password: the hub checks them with its worlds (`/internal/hub/claim`), creates the hub account with
that password and links the player, in every world where the same name and password match. Nobody else can register
such a name on the hub (`name_in_world`). A hub account made under another name links a player later: on the first
visit the world answers `link_required`, and the player gives that player's old password once.
Players from the hub have no password in the world: they log in through the hub, and their name comes from it.

## Founders and badges

Hub administrators (`OVIAN_HUB_ADMIN_USERS`) manage these from the Admin screen of either client (*Hub*):

- **Founders**: any account can be made a founder. Founders are numbered in order (Founder #1, #2, …; a number
  can also be given by hand) and get the founder badges: every badge of kind `founder`, or the ones chosen.
  Taking founder status back removes those badges.
- **Badges**: a catalogue of `id`, name, icon (an emoji), colour, kind and order. Kinds:
  - `founder`: given with founder status;
  - `patron`: given and taken back automatically with a Patreon pledge (`patreon_tier`: a tier id, or `*` for any
    active pledge);
  - `award`: given by hand, with an optional note.
- Badges show next to player names in every world: profiles, rankings, the player's own settings. When they change,
  the hub tells each world the account plays in; worlds also refresh them at each login.

## Patreon

Patrons get badges, and early access to worlds that allow it. Nothing that changes the balance of the game.

1. On Patreon, *Creator portal → Developers → Create client* (<https://www.patreon.com/portal/registration/register-clients>).
   Redirect URI: the hub's public address followed by `/api/v1/patreon/callback`, e.g.
   `https://empires.ofthepast.org/hub/api/v1/patreon/callback`.
2. Give the hub the client's id and secret, and your campaign id (so only pledges to your campaign count):
   `OVIAN_HUB_PATREON_CLIENT_ID`, `OVIAN_HUB_PATREON_CLIENT_SECRET`, `OVIAN_HUB_PATREON_CAMPAIGN_ID`.
3. In the same portal, add a webhook to `…/hub/api/v1/patreon/webhook` with the triggers `members:create`,
   `members:update`, `members:delete`, `members:pledge:create`, `members:pledge:update` and `members:pledge:delete`;
   put its secret in `OVIAN_HUB_PATREON_WEBHOOK_SECRET`. The webhook keeps pledges current: a patron who stops
   pledging loses the patron badges.
4. Create `patron` badges for your tiers (Admin → Hub → Badges; the tier ids are in the webhook payloads, or in
   the Patreon API). The hub starts with one, `patron`, for any active pledge.

A player links Patreon from *Settings → Account*: Patreon asks them to allow access, then sends them back to the site.

## Worlds

The hub lists worlds with a status:

| status | in the list | new players | players already there |
|---|---|---|---|
| `upcoming` | yes | no | no |
| `open` | yes | yes | yes |
| `closed` | yes | no | yes |
| `ended` | 30 days after `ends_at` | no | no |

`founders_only` opens a world to founders first (and to patrons too with `patrons_early`): an early-access period.
Turn it off to open the world to everyone.

Each world has two addresses:

- `api_url`, where browsers reach its API: `/` for the main world of the site, `/w/w3` for another world served
  through the site, or a full origin (`https://w3.example.org`) for a world elsewhere;
- `internal_url`, where the hub reaches it to push badges (`http://server:8000`, `http://server-w3:8000`, …).

Worlds can be added from the Admin screen, or declared at startup with
`OVIAN_HUB_WORLDS="w2|Antiquity|/|http://server:8000;w3|Isles|/w/w3|http://server-w3:8000"`
(id|name|api_url|internal_url; it creates them, or updates their addresses).

## Running it with Docker

On the main stack (`.env`):

```sh
COMPOSE_PROFILES=hub                       # with others: COMPOSE_PROFILES=bots,hub
OVIAN_HUB_JWT_SECRET=<random, 32+ characters>
OVIAN_HUB_WORLD_SECRET=<random, 32+ characters>   # the same value in every world
OVIAN_HUB_ADMIN_USERS=<your hub username>
OVIAN_HUB_WORLDS=w2|Antiquity|/|http://server:8000
OVIAN_HUB_INTERNAL_URL=http://hub:8000     # how worlds reach the hub
OVIAN_HUB_UPSTREAM=http://hub:8000         # the web front ends serve the hub at /hub/
OVIAN_PUBLIC_HUB_URL=/hub                  # turns the hub login on in both clients
OVIAN_HUB_PUBLIC_URL=https://empires.ofthepast.org
OVIAN_HUB_PUBLIC_API_URL=https://empires.ofthepast.org/hub
```

```sh
docker compose exec db createdb -U ovian ovian_hub
docker compose up -d --build hub server web diorama
```

A further world on the same machine runs its own server and broker next to the main stack
(`docker-compose.world.yml`), with the same database server:

```sh
cp worlds/example.env worlds/w3.env        # set its id, pack, speed, secrets
docker compose exec db createdb -U ovian ovian_w3
docker compose -p ovian-w3 --env-file worlds/w3.env -f docker-compose.world.yml up -d --build
```

Then route it through the front ends, list it on the hub, and restart them:

```sh
OVIAN_WORLDS=w3=http://server-w3:8000|http://broker-w3:9001          # API at /w/w3/, broker at /w/w3/mqtt
OVIAN_HUB_WORLDS=w2|Antiquity|/|http://server:8000;w3|Isles|/w/w3|http://server-w3:8000
docker compose up -d hub web diorama
```

A world on another machine is a plain Ovian stack with `OVIAN_HUB_WORLD_SECRET` set and `OVIAN_HUB_INTERNAL_URL`
pointing at the hub's own address (not through the site: the site never forwards `/internal/` paths). List it on
the hub with its public origin as `api_url`.

On Netlify, set the repository variables `OVIAN_HUB_ORIGIN` and `OVIAN_WORLDS` (`w3=https://w3.example.org …`);
see [deploy-netlify.md](deploy-netlify.md). Netlify cannot carry WebSockets, so each world's broker must be
reachable directly over `wss://` (its `OVIAN_MQTT_PUBLIC_URL`).

`OVIAN_LOCAL_REGISTRATION=false` closes a world's own sign-up page, so new players come only through the hub.
The AI rulers and personal access tokens keep working with world accounts.

## Spawning worlds from the hub

With the `hub` profile the stack also runs the **spawner**, the one service with write access to Docker. Hub
administrators create worlds from *Admin → Hub → Worlds → Spawn a world here*: id, name, pack, speed, a **mode** and
any **overrides**. The spawner writes `worlds/<id>.env` (fresh secrets) and `worlds/<id>.yaml` (the overrides), creates
the database, and runs `docker-compose.world.yml` with the images the main stack built. The world appears on the hub's
list at once and is reachable at `/w/<id>/` with no restart: the front ends look `server-<id>` and `broker-<id>` up
live. *Stop* stops its containers (the database stays) and marks it closed; *Start* brings them back.

Modes are presets of overrides (`GET /api/v1/settings/modes` on any world):

| mode | in short |
|---|---|
| `hybrid` | the pack as it is |
| `pve` | no war between players (`pvp.enabled: false`); more camps, a stronger horde, a week of protection; no battle victory |
| `pvp` | no camps or horde; a day of protection; abandoned cities fall in three days; battles and conquest count |

**Overrides** are a `{world: {...}, village: {...}, buildings: {...}, extensions: {...}}` document merged onto the
pack when the world's server starts (`OVIAN_OVERRIDES_FILE`): nested keys merge, `null` removes a group, which
switches features that need their group off (`GET /api/v1/settings/schema` lists every group, its code defaults and
whether leaving it out turns it off). `buildings` maps a building id to the keys to change, for example
`buildings: {wonder: {cost: {factor: 1.2}}, storehouse: {max_level: 25}}`; `village` reaches `base_storage`,
`storage_speed_exponent`, the start resources and the growth phases.
A world made by hand uses the same file: point `OVIAN_OVERRIDES_FILE` at it.

Settings: `OVIAN_SPAWNER_KEY` (shared by the hub and the spawner), `OVIAN_REPO_DIR` (this checkout's path on the
host, default `/srv/ovian`; the spawner mounts it at the same path), and the hub's `OVIAN_HUB_SPAWNER_URL`
(`http://spawner:8000`). The spawner only creates and stops: removing a world's containers and database is done by hand
(`docker compose -p ovian-<id> down`, `dropdb`).

## The hub API

`/hub/docs` lists it. In short:

| | |
|---|---|
| `POST /auth/register`, `POST /auth/login` | hub account; returns a hub token |
| `GET /me`, `POST /me/password` | the account, its badges, Patreon link and worlds |
| `GET /worlds`, `GET /me/worlds` | the list; the second says where the account plays and may enter |
| `POST /worlds/{id}/ticket` | a ticket for that world |
| `GET /accounts/{name}`, `GET /founders`, `GET /badges` | public profiles, the founders' roll, the badge catalogue |
| `GET /patreon/connect`, `DELETE /me/patreon` | link and unlink Patreon |
| `/admin/accounts…`, `/admin/badges…`, `/admin/worlds…` | administration |

In a world: `POST /auth/hub {ticket, tribe?, username?}` and `POST /auth/hub/link {ticket, password}`.
