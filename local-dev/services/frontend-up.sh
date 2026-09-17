#!/usr/bin/env bash
# frontend: standalone Podman pod serving the static React/Vite UI via nginx (see
# frontend/Dockerfile), together with ui-api (see ui-api/Dockerfile) — the FastAPI
# backend the UI calls. Both are built from source (context = repo root), same as
# eval-service-up.sh / eval-listener-up.sh. They share this pod's network namespace,
# so nginx proxies /api/ to ui-api over plain localhost (see frontend/nginx.conf.template
# and ui-api/README.md) rather than needing a separate published port for ui-api.
#
# Requires fluxnova-up.sh already running for the UI's API calls to work once ui-api
# grows Fluxnova-backed routes (the pod starts fine either way). fluxnova-local runs
# on --network host (see OTEL-EXPORT-INVESTIGATION.md at the repo root), so this pod
# also runs on --network host to reach it via plain localhost — same reasoning as
# eval-service-up.sh/observability-up.sh (host.containers.internal from a
# bridge-networked pod cannot reach a --network host container on Podman Desktop for
# Windows).
#
# Usage (from this directory):
#   ./frontend-up.sh
#   ./frontend-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

POD_NAME="${FRONTEND_POD_NAME:-frontend-local}"
FRONTEND_IMAGE_NAME="${FRONTEND_IMAGE:-frontend:local}"
UI_API_IMAGE_NAME="${UI_API_IMAGE:-ui-api:local}"
# See eval-service-up.sh for why `pwd -W` is used here (Git Bash/MSYS on Windows).
REPO_ROOT="$(cd ../.. && { pwd -W 2>/dev/null || pwd; })"
LOCAL_DEV_DIR="$(cd .. && pwd)"

if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

FRONTEND_PORT="${FRONTEND_PORT:-8081}"
UI_API_PORT="${UI_API_PORT:-8090}"
# This pod runs on --network host (see header), so ui-api (shares this netns) is
# reached via plain localhost, and ui-api in turn reaches Fluxnova via localhost too.
FRONTEND_API_PROXY_PASS="${FRONTEND_API_PROXY_PASS:-http://localhost:${UI_API_PORT}}"

# Only build when the image is missing, so repeated up-runs don't pay the build cost.
# Force a rebuild after changing frontend/ or ui-api/ with REBUILD=1.
if [ "${REBUILD:-}" = "1" ] || ! podman image exists "$FRONTEND_IMAGE_NAME"; then
  echo "Building $FRONTEND_IMAGE_NAME..."
  podman build -f "$REPO_ROOT/frontend/Dockerfile" -t "$FRONTEND_IMAGE_NAME" "$REPO_ROOT"
else
  echo "Image '$FRONTEND_IMAGE_NAME' already exists — skipping build (REBUILD=1 to force)."
fi

if [ "${REBUILD:-}" = "1" ] || ! podman image exists "$UI_API_IMAGE_NAME"; then
  echo "Building $UI_API_IMAGE_NAME..."
  podman build -f "$REPO_ROOT/ui-api/Dockerfile" -t "$UI_API_IMAGE_NAME" "$REPO_ROOT"
else
  echo "Image '$UI_API_IMAGE_NAME' already exists — skipping build (REBUILD=1 to force)."
fi

# Idempotent: if the pod already exists, just make sure it's started rather than
# failing on `podman pod create`/`podman run` name clashes. As with eval-service-up.sh,
# recreate it (./frontend-down.sh first) to pick up fresh images after a REBUILD.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' on --network host (nginx binds :${FRONTEND_PORT} directly — see header)..."
  podman pod create --name "$POD_NAME" --network host

  echo "Starting ui-api..."
  podman run -d --pod "$POD_NAME" --name ui-api \
    -e UI_API_PORT="$UI_API_PORT" \
    "$UI_API_IMAGE_NAME"

  echo "Starting frontend..."
  podman run -d --pod "$POD_NAME" --name frontend \
    -e API_PROXY_PASS="$FRONTEND_API_PROXY_PASS" \
    -e LISTEN_PORT="$FRONTEND_PORT" \
    "$FRONTEND_IMAGE_NAME"
fi

echo
echo "Frontend UI:   http://localhost:${FRONTEND_PORT}"
echo "ui-api:        http://localhost:${UI_API_PORT} (proxied by the frontend at /api/)"
echo "Logs:          podman logs -f frontend   /   podman logs -f ui-api"
echo "Stop/remove:   ./frontend-down.sh"
