#!/bin/sh
# Writes the client's runtime config, and the routes to the hub and to further worlds, from environment variables.
#   OVIAN_HUB_UPSTREAM=http://hub:8000          served at /hub/
#   OVIAN_WORLDS="w3=http://server-w3:8000|http://broker-w3:9001 w4=https://w4.example.org"
#                                                each served at /w/<id>/ (API) and /w/<id>/mqtt (broker, optional)
set -eu
skins=$(printf '%s' "$OVIAN_SKINS" | sed 's/[^,][^,]*/"&"/g')
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiUrl": "${OVIAN_PUBLIC_API_URL}",
  "mqttUrl": "${OVIAN_PUBLIC_MQTT_URL}",
  "hubUrl": "${OVIAN_PUBLIC_HUB_URL:-}",
  "skin": "${OVIAN_DEFAULT_SKIN}",
  "skins": [${skins}],
  "ledgerUrl": "${OVIAN_LEDGER_URL:-}",
  "dioramaUrl": "${OVIAN_DIORAMA_URL:-}",
  "mcpUrl": "${OVIAN_MCP_URL:-}"
}
JSON

mkdir -p /etc/nginx/ovian
conf=/etc/nginx/ovian/routes.conf
: > "$conf"
proxy='proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme;'
if [ -n "${OVIAN_HUB_UPSTREAM:-}" ]; then
  echo "location /hub/ { proxy_pass ${OVIAN_HUB_UPSTREAM%/}/; $proxy }" >> "$conf"
  echo "location /hub/api/v1/internal/ { return 404; }" >> "$conf"
fi
for w in $(printf '%s' "${OVIAN_WORLDS:-}" | tr ',;' '  '); do
  id=${w%%=*}; rest=${w#*=}
  api=${rest%%|*}; mqtt=""
  case "$rest" in *"|"*) mqtt=${rest#*|} ;; esac
  echo "location /w/$id/ { proxy_pass ${api%/}/; $proxy }" >> "$conf"
  echo "location /w/$id/internal/ { return 404; }" >> "$conf"
  echo "location /w/$id/api/v1/internal/ { return 404; }" >> "$conf"
  if [ -n "$mqtt" ]; then
    echo "location = /w/$id/mqtt { proxy_pass ${mqtt%/}/mqtt; proxy_http_version 1.1; proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection \$connection_upgrade; proxy_read_timeout 1h; }" >> "$conf"
  fi
done
