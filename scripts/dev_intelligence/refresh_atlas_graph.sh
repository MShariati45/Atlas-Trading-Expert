#!/bin/sh
set -eu
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"
GRAPHIFY_BIN="$HOME/.local/bin/graphify"
export PYTHONHASHSEED=0
export GRAPHIFY_MAX_WORKERS=2

if [ -f graphify-out/graph.json ]; then
  "$GRAPHIFY_BIN" update "$REPO" --no-cluster
else
  "$GRAPHIFY_BIN" extract atlas2 --code-only --no-cluster --max-workers 2 --out .
fi

"$GRAPHIFY_BIN" cluster-only . --no-label --no-viz
