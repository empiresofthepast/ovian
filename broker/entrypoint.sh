#!/bin/sh
set -eu
: "${OVIAN_INTERNAL_KEY:?OVIAN_INTERNAL_KEY must be set}"
OVIAN_AUTH_HOST="${OVIAN_AUTH_HOST:-server}"
OVIAN_AUTH_PORT="${OVIAN_AUTH_PORT:-8000}"
mkdir -p /etc/mosquitto
sed -e "s|\${OVIAN_AUTH_HOST}|${OVIAN_AUTH_HOST}|g" \
    -e "s|\${OVIAN_AUTH_PORT}|${OVIAN_AUTH_PORT}|g" \
    -e "s|\${OVIAN_INTERNAL_KEY}|${OVIAN_INTERNAL_KEY}|g" \
    /mosquitto/ovian/mosquitto.conf.template > /etc/mosquitto/mosquitto.conf
exec /usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf
