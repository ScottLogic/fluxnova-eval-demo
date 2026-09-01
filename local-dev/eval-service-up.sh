#!/usr/bin/env bash
# eval-service-worker: standalone Podman pod that subscribes to the Camunda/Fluxnova
# external-task topic (default agent-output-eval) and scores completed agentic
# subprocess runs against the decision_quality MLflow judge. See
# EVAL-SERVICE-WORKER-PLAN.md at the repo root for background/scope.
#
# Requires fluxnova-local and mlflow-local (fluxnova-up.sh / mlflow-up.sh) already
# running on the shared fluxnova-dev network — this worker reaches both by pod name,
# overriding the image's localhost-based defaults via EVAL_SERVICE_* env vars below
# (see src/eval_service_worker/config.py for the full list of settings/defaults).
#
# Usage (from this directory):
#   ./eval-service-up.sh
#   ./eval-service-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

POD_NAME="${EVAL_SERVICE_POD_NAME:-eval-service-local}"
IMAGE_NAME="${EVAL_SERVICE_IMAGE:-eval-service-worker:local}"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"
# `pwd -W` (Git Bash/MSYS only) prints the Windows-drive form (C:/dev/...) instead of
# the Unix-style form (/c/dev/...) `pwd` gives by default. podman.exe is a native
# Windows binary — combined with MSYS_NO_PATHCONV=1 above (needed to stop MSYS from
# mangling the *container-side* paths used elsewhere), an unconverted Unix-style path
# here gets double-prefixed into garbage like "C:\c\dev\..." when used as a build
# context. Falls back to plain `pwd` on non-Windows shells where `-W` isn't supported.
REPO_ROOT="$(cd .. && { pwd -W 2>/dev/null || pwd; })"

# Load .env (KEY=VALUE lines) if present.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Reach the sibling pods by container/pod name on the shared network, not localhost.
EVAL_SERVICE_FLUXNOVA_URL="${EVAL_SERVICE_FLUXNOVA_URL:-http://fluxnova-local:8080/engine-rest}"
EVAL_SERVICE_TRACKING_URI="${EVAL_SERVICE_TRACKING_URI:-http://mlflow-local:5000}"

podman network create --ignore "$DEV_NETWORK"

echo "Building $IMAGE_NAME..."
podman build -f "$REPO_ROOT/eval-service-worker/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"

echo "Creating pod '$POD_NAME'..."
podman pod create --name "$POD_NAME" \
  --network "$DEV_NETWORK" \
  --add-host host.containers.internal:host-gateway

echo "Starting eval-service-worker..."
podman run -d --pod "$POD_NAME" --name eval-service-worker \
  -e EVAL_SERVICE_FLUXNOVA_URL="$EVAL_SERVICE_FLUXNOVA_URL" \
  -e EVAL_SERVICE_TRACKING_URI="$EVAL_SERVICE_TRACKING_URI" \
  "$IMAGE_NAME"

echo
echo "Worker running. Topic: agent-output-eval (override with EVAL_SERVICE_TOPIC)"
echo "Logs:          podman logs -f eval-service-worker"
echo "Stop/remove:   ./eval-service-down.sh"
