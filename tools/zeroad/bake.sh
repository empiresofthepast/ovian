#!/bin/sh
# Bake 0 A.D. art for the diorama front end into web/projects/diorama/public/art (gitignored), in Docker.
set -e
cd "$(dirname "$0")/../.."
out=${1:-web/projects/diorama/public/art}
mkdir -p "$out"
docker build -q -t ovian-zeroad -f docker/zeroad.Dockerfile tools/zeroad >/dev/null
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v ovian-0ad:/cache -v "$PWD:/w" -w /w/tools/zeroad ovian-zeroad sh -c \
  "./fetch.sh /cache/repo diorama.yaml art && python bake.py --zeroad /cache/repo --config diorama.yaml --content /w/content --out /w/$out"
