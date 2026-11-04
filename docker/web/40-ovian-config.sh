#!/bin/sh
# Writes the client's runtime config from environment variables.
set -eu
skins=$(printf '%s' "$OVIAN_SKINS" | sed 's/[^,][^,]*/"&"/g')
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiUrl": "${OVIAN_PUBLIC_API_URL}",
  "mqttUrl": "${OVIAN_PUBLIC_MQTT_URL}",
  "skin": "${OVIAN_DEFAULT_SKIN}",
  "skins": [${skins}],
  "ledgerUrl": "${OVIAN_LEDGER_URL:-}",
  "dioramaUrl": "${OVIAN_DIORAMA_URL:-}",
  "mcpUrl": "${OVIAN_MCP_URL:-}"
}
JSON
