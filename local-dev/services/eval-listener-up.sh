#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
POD_NAME="${EVAL_LISTENER_POD_NAME:-eval-listener-local}"
IMAGE_NAME="${EVAL_LISTENER_IMAGE:-eval-trace-listener:local}"
require_http "http://localhost:${MLFLOW_PORT}/version" mlflow
if [ "${REBUILD:-}" = 1 ] || ! podman image exists "$IMAGE_NAME"; then
  podman build -f "$REPO_ROOT/eval-trace-listener/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
fi
if ! start_existing_pod "$POD_NAME" eval-trace-listener; then
  podman pod create --name "$POD_NAME" --network "$DEV_NETWORK" >/dev/null
  podman run -d --pod "$POD_NAME" --name eval-trace-listener \
    -e EVAL_LISTENER_TRACKING_URI="${EVAL_LISTENER_TRACKING_URI:-http://${MLFLOW_POD_NAME}:5000}" \
    -e EVAL_LISTENER_EXPERIMENT_NAME="${EVAL_LISTENER_EXPERIMENT_NAME:-$EVAL_SERVICE_EXPERIMENT_NAME}" \
    -e LLM_JUDGE_PROVIDER="$LLM_JUDGE_PROVIDER" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e OLLAMA_API_BASE="$OLLAMA_CONTAINER_URL" \
    "$IMAGE_NAME"
fi
echo "Listener started. Logs: podman logs -f eval-trace-listener"
