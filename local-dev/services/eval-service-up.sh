#!/usr/bin/env bash
# eval-service-worker: standalone Podman pod that subscribes to the Camunda/Fluxnova
# external-task topic (default agent-output-eval) and scores completed agentic
# subprocess runs against the decision_quality MLflow judge. See
# EVAL-SERVICE-WORKER-PLAN.md at the repo root for background/scope.
#
# Requires fluxnova-local and mlflow-local (fluxnova-up.sh / mlflow-up.sh) already
# running. fluxnova-local runs on --network host (see OTEL-EXPORT-INVESTIGATION.md at
# the repo root: running Fluxnova in any isolated Podman network namespace silently
# breaks the OpenTelemetry Java SDK's OTLP export), so this pod also runs on
# --network host to reach it via plain localhost — on Podman Desktop for Windows
# (gvproxy-backed VM), host.containers.internal/host-gateway as seen from a
# *bridge*-networked pod cannot reach a --network host container in the same VM
# (gvproxy routes it out toward the Windows side instead of back into the VM's main
# netns), which silently starved this worker's fetchAndLock calls. Being on
# --network host also means mlflow-local (normally reached by pod name on the shared
# bridge network) must instead be reached via its published host port. Overriding the
# image's localhost-based defaults via EVAL_SERVICE_* env vars below (see
# src/eval_service_worker/config.py for the full list of settings/defaults).
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
# `pwd -W` (Git Bash/MSYS only) prints the Windows-drive form (C:/dev/...) instead of
# the Unix-style form (/c/dev/...) `pwd` gives by default. podman.exe is a native
# Windows binary — combined with MSYS_NO_PATHCONV=1 above (needed to stop MSYS from
# mangling the *container-side* paths used elsewhere), an unconverted Unix-style path
# here gets double-prefixed into garbage like "C:\c\dev\..." when used as a build
# context. Falls back to plain `pwd` on non-Windows shells where `-W` isn't supported.
# This script now sits in local-dev/services/, so the repo root is two levels up.
REPO_ROOT="$(cd ../.. && { pwd -W 2>/dev/null || pwd; })"
# .env lives in the parent local-dev directory.
LOCAL_DEV_DIR="$(cd .. && pwd)"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

# This pod runs on --network host (see header), so both sibling pods are reached via
# localhost rather than by pod name: fluxnova-local binds :8080 directly (also
# --network host), and mlflow-local is reached via its published host port.
EVAL_SERVICE_FLUXNOVA_URL="${EVAL_SERVICE_FLUXNOVA_URL:-http://localhost:8080/engine-rest}"
EVAL_SERVICE_TRACKING_URI="${EVAL_SERVICE_TRACKING_URI:-http://localhost:${MLFLOW_PORT:-5000}}"
# EVAL_SERVICE_EXPERIMENT_NAME (the MLflow experiment the worker reads traces from) is
# sourced from .env above — it must match where the OTel collector writes traces
# (MLFLOW_EXPERIMENT_ID). Kept in .env, not hardcoded here, so compose.yaml uses the
# same source of truth.

# Only build when the image is missing, so repeated up-runs (e.g. after changing
# only BPMN/config/runner code) don't pay the pip-install cost. Force a rebuild
# after changing eval-service-worker/ or fluxnova-mlflow-dataset/ with REBUILD=1.
if [ "${REBUILD:-}" = "1" ] || ! podman image exists "$IMAGE_NAME"; then
  echo "Building $IMAGE_NAME..."
  podman build -f "$REPO_ROOT/eval-service-worker/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
else
  echo "Image '$IMAGE_NAME' already exists — skipping build (REBUILD=1 to force)."
fi

# Idempotent: if the pod already exists (e.g. this script was run before), just make
# sure it's started rather than failing on `podman pod create`/`podman run` name clashes.
# Note: an existing pod is only *started* here, so to pick up a fresh image after a
# REBUILD you must recreate it — run ./eval-service-down.sh first, then this script.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' on --network host (to reach fluxnova-local's" \
    "own --network host binding directly via localhost — see header)..."
  podman pod create --name "$POD_NAME" --network host

  echo "Starting eval-service-worker..."
  # MLFLOW_DISABLE_TELEMETRY: MLflow's background telemetry thread can deadlock
  # against evaluate()'s autolog import hooks (each holds an import lock the other
  # needs), freezing the worker mid-task with the external task left locked.
  podman run -d --pod "$POD_NAME" --name eval-service-worker \
    -e MLFLOW_DISABLE_TELEMETRY=true \
    -e OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
    -e EVAL_SERVICE_FLUXNOVA_URL="$EVAL_SERVICE_FLUXNOVA_URL" \
    -e EVAL_SERVICE_TRACKING_URI="$EVAL_SERVICE_TRACKING_URI" \
    -e EVAL_SERVICE_EXPERIMENT_NAME="$EVAL_SERVICE_EXPERIMENT_NAME" \
    -e EVAL_SERVICE_LOCK_DURATION_MS="${EVAL_SERVICE_LOCK_DURATION_MS:-600000}" \
    "$IMAGE_NAME"
fi

echo
echo "Worker running. Topic: agent-output-eval (override with EVAL_SERVICE_TOPIC)"
echo "Reading traces from experiment: $EVAL_SERVICE_EXPERIMENT_NAME"
echo "Logs:          podman logs -f eval-service-worker"
echo "Stop/remove:   ./eval-service-down.sh"
