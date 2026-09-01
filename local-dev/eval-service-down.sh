#!/usr/bin/env bash
# Stops and removes the eval-service-local pod created by eval-service-up.sh.
set -uo pipefail

POD_NAME="${EVAL_SERVICE_POD_NAME:-eval-service-local}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
