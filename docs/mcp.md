# The MCP server: let an AI assistant run your cities

`mcp/ovian_mcp.py` is a [Model Context Protocol](https://modelcontextprotocol.io) server. With it,
Claude (or any MCP client) can read your cities and give orders for you, through the same public API
the game clients use. It runs as the `mcp` service, on port `OVIAN_MCP_PORT` (47002), at `/mcp`
(Streamable HTTP, stateless).

## Connecting

1. In the game, open **Settings → AI assistants** and create an access token. It starts with `ovp_`
   and is shown only once.
2. Add the server to your assistant. Claude Code:

   ```sh
   claude mcp add --transport http ovian http://<host>:47002/mcp --header "Authorization: Bearer ovp_…"
   ```

   Other clients take the same URL and header in their JSON config (Settings shows both).
3. Ask, for example: "Look at my cities and spend the resources on whatever grows production fastest."

## What it can do

| Tool | Does |
| --- | --- |
| `my_empire` | you and all your cities: resources, production, queues, armies on the move |
| `city` | one city in full: every site, troops, queues, omen, mood |
| `city_options` | what the city can build, upgrade, train and research now, with costs and times, or why not |
| `world_map` | cities and barbarian camps around a point, nearest first |
| `reports`, `read_report`, `quests` | reading |
| `build`, `train`, `research`, `cancel_job` | the city's queues |
| `demolish` | pull a building down for half its cost back |
| `build_embassy`, `build_overlord_site` | raise your embassy, cultural exchange or garrison in a vassal city |
| `levy_auxiliaries` | train a vassal's own troops in your garrison there |
| `excavate` | dig an empty site or a ruin for finds |
| `governors`, `hire_governor`, `appoint_governor`, `recall_governor` | governors and prefects |
| `send_troops` | attack, raid, reinforce, scout (with missions), also from a garrison in a vassal |
| `send_resources`, `answer_omen`, `claim_quest`, `rename_city` | the rest |

The server checks every order exactly as it does for the clients. `city_options` uses the
`GET /villages/{id}/options` endpoint, which is also there for your own scripts.

## Access tokens

- `POST /me/tokens {name}` creates one (the response carries the full `token`, once); `GET /me/tokens`
  lists them with their last use; `DELETE /me/tokens/{id}` revokes one. At most 10 per player.
- A token acts as its player everywhere except account settings: it cannot create tokens or change the
  username (`403 needs_login`). Bans apply to it as well.
- Only a SHA-256 hash is stored. Tokens never expire; revoke the ones you no longer use.
- Any `Authorization: Bearer ovp_…` request to the API works the same way, so tokens also suit scripts.

## Deployment

`OVIAN_MCP_PUBLIC_URL` is the URL the Settings page shows (default: this host on port 47002).
`OVIAN_MCP_HOSTS` (comma-separated) turns on Host-header checking against DNS rebinding.
Tokens travel in clear text over plain HTTP: put the server behind HTTPS before going public.
