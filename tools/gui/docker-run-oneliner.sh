#!/usr/bin/env bash
# One-liner: start Z-MAX Console in Docker
# Usage: bash tools/gui/docker-run.sh [studio|simple]
docker run --rm \
    -e DISPLAY=$DISPLAY \
    -e CONSOLE_MODE=${1:-studio} \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $HOME/.hermes:/home/xspace/.hermes:ro \
    $(docker build -q --build-arg UID=$(id -u) --build-arg GID=$(id -g) tools/gui/)
