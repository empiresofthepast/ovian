# AI rulers

`bots/ovian_bots.py` runs a handful of NPC kingdoms: ordinary accounts, played by
simple rules, that keep a young world from feeling empty. They are deliberately
friendly: they raid barbarian camps but never attack, scout or pressure human players.

They are a client like any other. They use only the public HTTP API
(`/api/v1`, the same one the web clients use) and never call admin endpoints, so
they cannot do anything a player could not do.

## Running

The service is in `docker-compose.yml` behind the `bots` profile.

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMPOSE_PROFILES` | | Set to `bots` so `docker compose up` starts the service. |
| `OVIAN_BOTS` | six rulers (see below) | `Name:tribe:persona;...`. Tribe ids come from `GET /api/v1/content` (`tribes`). |
| `OVIAN_BOT_USERS` | | Server setting. Comma-separated usernames flagged as bots on login (`bot: true` in rankings, map and player pages). List the same names. |
| `OVIAN_BOT_PASSWORD` | (required) | Password of every bot account. Keep it secret: anyone with it can play the bots. |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama on the Docker host. |
| `OLLAMA_MODEL` | `hf.co/prism-ml/Bonsai-1.7B-gguf:Q1_0` | Any Ollama model. Pull it first: `ollama pull <model>`. |
| `BOTS_TICK_SECONDS` | `60` | Seconds between two turns. |
| `BOTS_CHAT_EVERY_MINUTES` | `45` | Average minutes between two proclamations (±30%). `0` turns them off. |

```bash
docker compose up -d server          # after changing OVIAN_BOT_USERS
docker compose up -d --build bots
docker compose logs -f bots
```

On first start each ruler registers (or logs in), names its city after its
capital (Athens, Carthage, Alesia...) and starts playing. Add a ruler by
appending it to `OVIAN_BOTS` and `OVIAN_BOT_USERS` and restarting both services.
Stopping the service leaves the accounts in the world; they simply stop playing.

## Personas

| Persona | Voice | Government | Play |
| --- | --- | --- | --- |
| `statesman` | eloquent, loves trade and great buildings | Republic | temple and market early |
| `general` | strategy, discipline, glory | Monarchy | barracks early, raids from 20 troops |
| `warlord` | blunt tribal chief | Tyranny | barracks early, raids from 20 troops |
| `priest` | pious and calm | Theocracy | temple and market early |
| `builder` | roads, granaries, gardens | Oligarchy | temple and market early |

Any other text is used as a free description of the ruler's character (no government change).
The defaults are Pericles (athen, statesman), Hannibal (cart, general),
Vercingetorix (gaul, warlord), Ashoka (maur, priest), Cyrus (achae, builder) and
Boudica (brit, warlord).

## What a ruler does each turn

For each of its cities (`GET /villages/{id}`), with a few API calls at most:

1. **Omens**: answers a pending omen with an affordable choice. Martial rulers take
   the richest one, the others the one that pleases the people.
2. **Building**, while the build queue has room: storage when a resource is above
   85% of capacity, the fields of the scarcest resources, the growth building
   (`village.growth.building`) when the fields have caught up, then barracks,
   temple, market, houses and wall, up to levels that follow the centre. Costs and
   requirements are checked locally from the content pack before asking; the
   server's 409 refusals are expected and skipped.
3. **Training**: the cheapest infantry of its tribe it can train, when stores are
   over half full, with at most 40% of the stock, and only as many as food
   production can feed with a 25% margin.
4. **Raiding**: with 30 troops (20 for martial rulers) at home and no army out,
   sends 80% of them to raid the nearest barbarian camp (`/map`, villages with
   `camp_level`) that it can beat comfortably.
5. Now and then: picks its persona's government once (`/me/government`), and enters
   every contest of the festival when one is held (`/calendar`, `/festival/{contest}`),
   offering 10% of its stock in the resource contest.

## Chat

- Every `BOTS_CHAT_EVERY_MINUTES` one random ruler posts a proclamation to the
  `global` channel about something that really happened (a building begun, a raid,
  a new government, the season).
- Each turn the service reads `GET /chat/global`; when a player mentions a ruler by
  name, that ruler answers in one or two sentences. Only messages posted after the
  service started are answered, each once.

The text comes from Ollama (`/api/generate`, `num_predict` 80, temperature 0.8, 60 s
timeout, one request at a time). The system prompt asks for one or two short
sentences in character, without emojis or hashtags, and never to claim to be an AI.
The reply is cleaned (think tags, emojis, hashtags, more than two sentences) and
replaced by a canned line if Ollama is unreachable or the answer looks wrong.
The model runs on the CPU; the 1.7B Bonsai model answers in a few seconds.

## Limits

- One city each: the rulers do not settle or conquer new cities.
- They do not trade, research, use heroes or join alliances.
- They keep no memory between restarts beyond what the server stores.
