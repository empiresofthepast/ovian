#!/bin/sh
# Regenerate content/antiquity/pack.yaml from 0 A.D. data, in Docker.
# The 0 A.D. checkout is cached in the ovian-0ad volume (see fetch.sh).
set -e
cd "$(dirname "$0")/../.."
docker build -q -t ovian-zeroad -f docker/zeroad.Dockerfile tools/zeroad >/dev/null
docker run --rm -v ovian-0ad:/cache -v "$PWD:/w" -w /w/tools/zeroad ovian-zeroad sh -c \
  "./fetch.sh /cache/repo antiquity.yaml && python convert.py --zeroad /cache/repo --config antiquity.yaml --out /w/content/antiquity $*"
