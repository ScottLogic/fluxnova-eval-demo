#!/usr/bin/env bash
# frontend: standalone Podman pod serving the static React/Vite UI via nginx (see
# frontend/Dockerfile). Built from source (context = repo root), same as
# eval-service-up.sh / eval-listener-up.sh.
#
# Requires fluxnova-up.sh already running for the UI's API calls to work (the pod
# starts fine either way — nginx just proxies to a Fluxnova that isn't there yet).
# fluxnova-local runs on --network host (see OTEL-EXPORT-INVESTIGATION.md at the repo
# root), so this pod also runs on --network host to reach it via plain localhost —
# same reasoning as eval-service-up.sh/observability-up.sh (host.containers.internal
# from a bridge-networked pod cannot reach a --network host container on Podman
# Desktop for Windows).
#
# Usage (from this directory):
#   ./frontend-up.sh
#   ./frontend-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

POD_NAME="${FRONTEND_POD_NAME:-frontend-local}"
IMAGE_NAME="${FRONTEND_IMAGE:-frontend:local}"
# See eval-service-up.sh for why `pwd -W` is used here (Git Bash/MSYS on Windows).
REPO_ROOT="$(cd ../.. && { pwd -W 2>/dev/null || pwd; })"
LOCAL_DEV_DIR="$(cd .. && pwd)"

if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

FRONTEND_PORT="${FRONTEND_PORT:-8081}"
# This pod runs on --network host (see header), so Fluxnova is reached via localhost
# rather than by pod name.
FRONTEND_API_PROXY_PASS="${FRONTEND_API_PROXY_PASS:-http://localhost:8080/engine-rest/}"

# Only build when the image is missing, so repeated up-runs don't pay the npm/nginx
# build cost. Force a rebuild after changing frontend/ with REBUILD=1.
if [ "${REBUILD:-}" = "1" ] || ! podman image exists "$IMAGE_NAME"; then
  echo "Building $IMAGE_NAME..."
  podman build -f "$REPO_ROOT/frontend/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
else
  echo "Image '$IMAGE_NAME' already exists — skipping build (REBUILD=1 to force)."
fi

# Idempotent: if the pod already exists, just make sure it's started rather than
# failing on `podman pod create`/`podman run` name clashes. As with eval-service-up.sh,
# recreate it (./frontend-down.sh first) to pick up a fresh image after a REBUILD.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' on --network host (nginx binds :${FRONTEND_PORT} directly — see header)..."
  podman pod create --name "$POD_NAME" --network host

  echo "Starting frontend..."
  podman run -d --pod "$POD_NAME" --name frontend \
    -e API_PROXY_PASS="$FRONTEND_API_PROXY_PASS" \
    -e LISTEN_PORT="$FRONTEND_PORT" \
    "$IMAGE_NAME"
fi

echo
echo "Frontend UI:   http://localhost:${FRONTEND_PORT}"
echo "Proxying /api/ to: $FRONTEND_API_PROXY_PASS"
echo "Logs:          podman logs -f frontend"
echo "Stop/remove:   ./frontend-down.sh"
