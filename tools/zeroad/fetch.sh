#!/bin/sh
# Sparse, partial checkout of the 0 A.D. repository at the commit pinned in a config file.
# Only the data Ovian reads is checked out; LFS art is smudged for those paths only.
#   ./fetch.sh <dir> <config.yaml> [art]
set -e
dir=$1; cfg=$2; want=${3:-sim}
repo=$(python -c "import yaml,sys;print(yaml.safe_load(open('$cfg'))['source']['repo'])")
commit=$(python -c "import yaml,sys;print(yaml.safe_load(open('$cfg'))['source']['commit'])")
P=binaries/data/mods/public
if [ ! -d "$dir/.git" ]; then
  git clone --filter=blob:none --no-checkout "$repo" "$dir"
fi
cd "$dir"
git sparse-checkout init --no-cone 2>/dev/null || true
paths="/LICENSE.md /$P/simulation/templates/ /$P/simulation/data/civs/"
if [ "$want" = art ]; then
  paths="$paths /$P/art/LICENSE.txt /$P/art/actors/ /$P/art/variants/ /$P/art/materials/ /$P/art/meshes/ /$P/art/textures/skins/ /$P/art/textures/ui/ /$P/art/textures/terrain/"
fi
# shellcheck disable=SC2086
git sparse-checkout add $paths
if [ "$(git rev-parse HEAD 2>/dev/null)" != "$commit" ] || [ -n "$(git status --porcelain 2>/dev/null | head -1)" ]; then
  git fetch -q --filter=blob:none origin "$commit" 2>/dev/null || true
  git -c advice.detachedHead=false checkout -q "$commit"
fi
git checkout -q .
