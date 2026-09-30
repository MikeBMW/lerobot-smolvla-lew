#!/usr/bin/env bash
# Build & run Z-MAX Console Docker image
set -euo pipefail

CMD="${1:-studio}"  # studio or simple

cd "$(dirname "$0")"

echo "==> Building zmax-console ..."
docker build \
    --build-arg UID="$(id -u)" \
    --build-arg GID="$(id -g)" \
    -t zmax-console .

echo ""
echo "==> Running zmax-console (mode=$CMD) ..."
docker run --rm \
    -e DISPLAY="$DISPLAY" \
    -e CONSOLE_MODE="$CMD" \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$HOME/.hermes:/home/xspace/.hermes:ro" \
    zmax-console
