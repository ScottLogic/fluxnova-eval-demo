#!/usr/bin/env bash
# eval-trace-listener: standalone Podman pod that tails the MLflow experiment's trace
# store and scores newly-completed agent runs with the deterministic (trace-only)
# scorers. See eval-trace-listener/README.md at the repo root for background/scope.
#
# Requires mlflow-local (mlflow-up.sh) already running on the shared fluxnova-dev
# network — this listener reaches it by pod name, overriding the image's localhost-based
# defaults via EVAL_LISTENER_* env vars below (see
# eval-trace-listener/src/eval_trace_listener/config.py for the full list of settings).
# Unlike eval-service-up.sh it does NOT need fluxnova-local (it never calls the engine).
#
# Usage (from this directory):
#   ./eval-listener-up.sh
#   ./eval-listener-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

POD_NAME="${EVAL_LISTENER_POD_NAME:-eval-listener-local}"
IMAGE_NAME="${EVAL_LISTENER_IMAGE:-eval-trace-listener:local}"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"
# `pwd -W` (Git Bash/MSYS only) prints the Windows-drive form (C:/dev/...) — see the
# note in eval-service-up.sh for why an unconverted Unix-style path breaks the build
# context on Windows. This script sits in local-dev/services/, so the repo root is two
# levels up.
REPO_ROOT="$(cd ../.. && { pwd -W 2>/dev/null || pwd; })"
# .env lives in the parent local-dev directory.
LOCAL_DEV_DIR="$(cd .. && pwd)"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

# Reach the sibling MLflow pod by pod name on the shared network, not localhost.
EVAL_LISTENER_TRACKING_URI="${EVAL_LISTENER_TRACKING_URI:-http://mlflow-local:5000}"
# The experiment to tail must be the same one the OTel collector writes to
# (MLFLOW_EXPERIMENT_ID). Reuse eval-service-worker's .env value as the single source
# of truth so both eval services read the same experiment.
EVAL_LISTENER_EXPERIMENT_NAME="${EVAL_LISTENER_EXPERIMENT_NAME:-${EVAL_SERVICE_EXPERIMENT_NAME:-fluxnova-loanAssessmentEvalProcess}}"
# Selects the LLM provider for this listener's decision_quality/evidence_citation
# judges (see fluxnova_mlflow_dataset.scorers.LLM_JUDGE_PROVIDER) — was previously
# left unset here, so the container silently fell back to that module's own
# "openai" default rather than actually reading .env's value. Wired through
# explicitly so switching .env's LLM_JUDGE_PROVIDER (e.g. to "ollama" for a fully
# local judge) actually takes effect. OPENAI_API_KEY is only required/read when
# this resolves to "openai".
LLM_JUDGE_PROVIDER="${LLM_JUDGE_PROVIDER:-openai}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
# Sample-rate control endpoint (see eval_trace_listener/control.py) — published on
# the host so a --network host container (e.g. ui-api, in the frontend-local pod)
# can reach it via host.containers.internal, same as eval-service-worker reaches
# fluxnova-local.
EVAL_LISTENER_CONTROL_PORT="${EVAL_LISTENER_CONTROL_PORT:-8092}"

podman network create --ignore "$DEV_NETWORK"

# Only build when the image is missing, so repeated up-runs don't pay the pip-install
# cost. Force a rebuild after changing eval-trace-listener/ or fluxnova-mlflow-dataset/
# with REBUILD=1.
if [ "${REBUILD:-}" = "1" ] || ! podman image exists "$IMAGE_NAME"; then
  echo "Building $IMAGE_NAME..."
  podman build -f "$REPO_ROOT/eval-trace-listener/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
else
  echo "Image '$IMAGE_NAME' already exists — skipping build (REBUILD=1 to force)."
fi

# Idempotent: if the pod already exists, just make sure it's started rather than failing
# on name clashes. Note: an existing pod is only *started* here, so to pick up a fresh
# image after a REBUILD you must recreate it — run ./eval-listener-down.sh first.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME'..."
  podman pod create --name "$POD_NAME" \
    --network "$DEV_NETWORK" \
    --add-host host.containers.internal:host-gateway \
    --publish "${EVAL_LISTENER_CONTROL_PORT}:${EVAL_LISTENER_CONTROL_PORT}"

  echo "Starting eval-trace-listener..."
  podman run -d --pod "$POD_NAME" --name eval-trace-listener \
    -e EVAL_LISTENER_TRACKING_URI="$EVAL_LISTENER_TRACKING_URI" \
    -e EVAL_LISTENER_EXPERIMENT_NAME="$EVAL_LISTENER_EXPERIMENT_NAME" \
    -e LLM_JUDGE_PROVIDER="$LLM_JUDGE_PROVIDER" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e EVAL_LISTENER_CONTROL_PORT="$EVAL_LISTENER_CONTROL_PORT" \
    "$IMAGE_NAME"
fi

echo
echo "Listener running. Tailing experiment: $EVAL_LISTENER_EXPERIMENT_NAME"
echo "Scoring agents:  see agent_names in the baked-in config.yaml (override with EVAL_LISTENER_AGENT_NAMES)"
echo "Sample rate:     GET/PUT http://localhost:${EVAL_LISTENER_CONTROL_PORT}/config (e.g. {\"sample_rate\": 0.5})"
echo "Logs:            podman logs -f eval-trace-listener"
echo "Stop/remove:     ./eval-listener-down.sh"
