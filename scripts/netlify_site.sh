#!/bin/sh
# Adds what nginx does in the Docker images to a built front end, for Netlify:
# config.json (runtime config), _redirects (API proxy, Angular routes) and _headers (caching).
#   API=https://api.example.org MQTT=wss://mqtt.example.org/mqtt ./scripts/netlify_site.sh web/dist/web/browser
# Env: API (required, where /api/* goes), MQTT, MCP, LEDGER, DIORAMA, SKIN (default parchment), SKINS.
set -eu
dir=$1
: "${API:?set API to the server origin, e.g. https://api.example.org}"
API=${API%/}
skins=$(printf '%s' "${SKINS:-parchment,nightwatch,aegean}" | sed 's/[^,][^,]*/"&"/g')

cat > "$dir/config.json" <<JSON
{
  "apiUrl": "",
  "mqttUrl": "${MQTT:-}",
  "skin": "${SKIN:-parchment}",
  "skins": [${skins}],
  "ledgerUrl": "${LEDGER:-}",
  "dioramaUrl": "${DIORAMA:-}",
  "mcpUrl": "${MCP:-}"
}
JSON

# Netlify proxies these to the game server, so the browser talks to one origin.
cat > "$dir/_redirects" <<EOF
/api/*          ${API}/api/:splat  200
/health         ${API}/health  200
/docs           ${API}/docs  200
/openapi.json   ${API}/openapi.json  200
/internal/*     /index.html  404
/*              /index.html  200
EOF

# Netlify revalidates everything by default (ETag), which suits index.html, config.json, the engine
# and the art manifest; only the content-hashed bundles are kept for good, and meshes and textures a day.
cat > "$dir/_headers" <<'EOF'
/*.wasm
  Content-Type: application/wasm
/art/m/*
  Cache-Control: public, max-age=86400
/art/t/*
  Cache-Control: public, max-age=86400
/*.dae
  Content-Type: model/vnd.collada+xml
/main-*.js
  Cache-Control: public, max-age=31536000, immutable
/chunk-*.js
  Cache-Control: public, max-age=31536000, immutable
/polyfills-*.js
  Cache-Control: public, max-age=31536000, immutable
/styles-*.css
  Cache-Control: public, max-age=31536000, immutable
EOF
echo "Netlify files written to $dir (API ${API})"
