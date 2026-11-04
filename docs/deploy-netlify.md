# Front ends on Netlify

The two web clients are static sites, so they can live on Netlify while the game server, broker and
database stay on your own machine. `.github/workflows/deploy-web.yml` builds both on every push to
`main` that touches the web, the engine, the content packs or the art tools (or by hand, *Run workflow*):

1. the engine in WebAssembly (Rust, wasm-bindgen 0.2.95);
2. the 0 A.D. art for the diorama (`tools/zeroad/bake.sh`, cached until its inputs change; the first run
   downloads part of the 0 A.D. repository and takes a while);
3. `ng build web` and `ng build diorama`, plus what nginx does in the Docker images
   (`scripts/netlify_site.sh`): `config.json`, `_redirects` and `_headers`;
4. `netlify deploy --prod` of each to its own site.

## Setup

1. On Netlify, create two empty sites (*Add new site → Deploy manually*, or `netlify sites:create`), one for
   the ledger and one for the diorama, and a personal access token (*User settings → Applications*).
2. In the GitHub repository, *Settings → Secrets and variables → Actions*:
   - secrets `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_LEDGER`, `NETLIFY_SITE_DIORAMA` (the sites' *Site ID*);
   - variable `OVIAN_API_ORIGIN`: the game server, e.g. `https://api.example.org`. Netlify forwards
     `/api/*` there, so the browser talks to one origin;
   - variable `OVIAN_MQTT_URL`: the broker's WebSocket, `wss://...` (see below);
   - optional variables `OVIAN_MCP_URL`, `OVIAN_LEDGER_URL`, `OVIAN_DIORAMA_URL`.
3. Point your domains at the sites in Netlify (*Domain management*).

Without the secrets the workflow still builds both clients, and skips the deploy with a warning.

## Things Netlify does not do

- **Live updates.** Netlify cannot forward WebSockets, so the broker must be reachable by the browser
  directly, over TLS (`wss://`): a page served over https may not open `ws://`. Put a TLS proxy (Caddy,
  nginx with Let's Encrypt) in front of the broker's port 9001 (host port `OVIAN_MQTT_WS_PORT`).
- **Encryption to the server.** Netlify forwards `/api/*` to `OVIAN_API_ORIGIN` as given. With a plain
  `http://` origin, passwords and tokens cross the internet unencrypted between Netlify and your server:
  use an `https://` origin.
- **CORS.** Not needed: the API is reached through the site's own origin.
