#!/bin/sh
# Adds what nginx does in the Docker images to a built front end, for Netlify:
# config.json (runtime config), _redirects (API proxy, Angular routes) and _headers (caching).
#   API=https://api.example.org MQTT=wss://mqtt.example.org/mqtt ./scripts/netlify_site.sh web/dist/diorama/browser
# If the directory holds the ledger in a subfolder (ledger/, built with --base-href /ledger/), it gets the
# same config.json and its own Angular fallback: both clients share one origin, and so one login.
# Env: API (required, where /api/* goes), MQTT, MCP, LEDGER, DIORAMA, SKIN (default parchment), SKINS,
#      HUB (the hub's origin, served at /hub/), WORLDS ("w3=https://w3.example.org w4=..." each served at /w/<id>/;
#      Netlify cannot carry WebSockets, so each world's broker must be public: its OVIAN_MQTT_PUBLIC_URL).
set -eu
dir=$1
: "${API:?set API to the server origin, e.g. https://api.example.org}"
API=${API%/}
skins=$(printf '%s' "${SKINS:-parchment,nightwatch,aegean}" | sed 's/[^,][^,]*/"&"/g')
sub=""
if [ -f "$dir/ledger/index.html" ]; then sub=ledger; fi

cat > "$dir/config.json" <<JSON
{
  "apiUrl": "",
  "mqttUrl": "${MQTT:-}",
  "hubUrl": "${HUB:+/hub}",
  "skin": "${SKIN:-parchment}",
  "skins": [${skins}],
  "ledgerUrl": "${LEDGER:-}",
  "dioramaUrl": "${DIORAMA:-}",
  "mcpUrl": "${MCP:-}"
}
JSON
if [ -n "$sub" ]; then cp "$dir/config.json" "$dir/$sub/config.json"; fi

# Netlify proxies these to the game server, so the browser talks to one origin.
{
  echo "/internal/*     /index.html  404"
  echo "/api/v1/internal/*  /index.html  404"
  if [ -n "${HUB:-}" ]; then
    echo "/hub/api/v1/internal/*  /index.html  404"
    echo "/hub/*          ${HUB%/}/:splat  200"
  fi
  for w in $(printf '%s' "${WORLDS:-}" | tr ',;' '  '); do
    id=${w%%=*}; origin=${w#*=}
    echo "/w/$id/internal/*  /index.html  404"
    echo "/w/$id/api/v1/internal/*  /index.html  404"
    echo "/w/$id/*        ${origin%/}/:splat  200"
  done
  echo "/api/*          ${API}/api/:splat  200"
  echo "/health         ${API}/health  200"
  echo "/docs           ${API}/docs  200"
  echo "/openapi.json   ${API}/openapi.json  200"
  if [ -n "$sub" ]; then echo "/$sub/*  /$sub/index.html  200"; fi
  echo "/*              /index.html  200"
} > "$dir/_redirects"

# Netlify revalidates everything by default (ETag), which suits index.html, config.json, the engine
# and the art manifest; only the content-hashed bundles are kept for good, and meshes and textures a day.
{
  printf '/*.wasm\n  Content-Type: application/wasm\n'
  printf '/*.dae\n  Content-Type: model/vnd.collada+xml\n'
  printf '/art/m/*\n  Cache-Control: public, max-age=86400\n'
  printf '/art/t/*\n  Cache-Control: public, max-age=86400\n'
  for p in "" ${sub:+"$sub/"}; do
    for f in 'main-*.js' 'chunk-*.js' 'polyfills-*.js' 'styles-*.css'; do
      printf '/%s%s\n  Cache-Control: public, max-age=31536000, immutable\n' "$p" "$f"
    done
  done
} > "$dir/_headers"
echo "Netlify files written to $dir (API ${API}${sub:+, with /$sub/})"
