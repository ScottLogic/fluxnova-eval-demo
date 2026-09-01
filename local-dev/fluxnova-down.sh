#!/usr/bin/env bash
# Stops and removes the fluxnova-local pod created by fluxnova-up.sh.
set -uo pipefail

POD_NAME="${POD_NAME:-fluxnova-local}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
