# Front ends on Netlify

The two web clients are static sites, so they can live on Netlify while the game server, broker and
database stay on your own machine. They are deployed as **one site**: the 3D diorama at `/` and the ledger
at `/ledger/`. Sharing an origin, they share the login too. `.github/workflows/deploy-web.yml` builds them
on every push to `main` that touches the web, the engine, the content packs or the art tools (or by hand,
*Run workflow*):

1. the engine in WebAssembly (Rust, wasm-bindgen 0.2.95);
2. the 0 A.D. art for the diorama (`tools/zeroad/bake.sh`, cached until its inputs change; the first run
   downloads part of the 0 A.D. repository and takes a while);
3. `ng build diorama` and `ng build web --base-href /ledger/`, the ledger copied into `ledger/`, plus what
   nginx does in the Docker images (`scripts/netlify_site.sh`): `config.json`, `_redirects` and `_headers`;
4. `netlify deploy --prod` of the result.

## Setup

1. On Netlify, create an empty site (*Add new site → Deploy manually*, or `netlify sites:create`) and a
   personal access token (*User settings → Applications*).
2. In the GitHub repository, *Settings → Secrets and variables → Actions*:
   - secrets `NETLIFY_AUTH_TOKEN` and `NETLIFY_SITE_ID` (the site's *Site ID*);
   - variable `OVIAN_API_ORIGIN`: the game server, e.g. `https://api.example.org`. Netlify forwards
     `/api/*` there, so the browser talks to one origin;
   - variable `OVIAN_MQTT_URL`: the broker's WebSocket, `wss://...` (see below);
   - optional variable `OVIAN_MCP_URL`;
   - with a hub ([worlds.md](worlds.md)): `OVIAN_HUB_ORIGIN` (served at `/hub/`, and turns the hub login on) and
     `OVIAN_WORLDS`, further worlds as `w3=https://w3.example.org w4=…` (served at `/w/<id>/`).
3. Point your domain at the site in Netlify (*Domain management*). The official world uses
   `empires.ofthepast.org`; its documentation is at `empiresofthepast.github.io`.

Without the secrets the workflow still builds both clients, and skips the deploy with a warning.

## Things Netlify does not do

- **Live updates.** Netlify cannot forward WebSockets, so the broker must be reachable by the browser
  directly, over TLS (`wss://`): a page served over https may not open `ws://`. Put a TLS proxy (Caddy,
  nginx with Let's Encrypt) in front of the broker's port 9001 (host port `OVIAN_MQTT_WS_PORT`).
- **Encryption to the server.** Netlify forwards `/api/*` to `OVIAN_API_ORIGIN` as given. With a plain
  `http://` origin, passwords and tokens cross the internet unencrypted between Netlify and your server:
  use an `https://` origin.
- **CORS.** Not needed: the API is reached through the site's own origin.
