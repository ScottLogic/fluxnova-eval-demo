#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
POD_NAME="${EVAL_SERVICE_POD_NAME:-eval-service-local}"
IMAGE_NAME="${EVAL_SERVICE_IMAGE:-eval-service-worker:local}"
if [ "$DEV_NETWORK_MODE" = host ]; then
  network_args=(--network host)
  engine_url="http://localhost:${FLUXNOVA_PORT}/engine-rest"
  tracking_uri="http://localhost:${MLFLOW_PORT}"
else
  network_args=(--network "$DEV_NETWORK")
  engine_url="http://${FLUXNOVA_POD_NAME}:8080/engine-rest"
  tracking_uri="http://${MLFLOW_POD_NAME}:5000"
fi
require_http "http://localhost:${FLUXNOVA_PORT}/engine-rest/engine" fluxnova
require_http "http://localhost:${MLFLOW_PORT}/version" mlflow
if [ "${REBUILD:-}" = 1 ] || ! podman image exists "$IMAGE_NAME"; then
  ensure_image docker.io/library/python:3.11-slim
  podman build --pull=never -f "$REPO_ROOT/eval-service-worker/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"
fi
if ! start_existing_pod "$POD_NAME" eval-service-worker; then
  create_pod "$POD_NAME" "${network_args[@]}"
  run_container -d --pod "$POD_NAME" --name eval-service-worker \
    -e EVAL_SERVICE_FLUXNOVA_URL="${EVAL_SERVICE_FLUXNOVA_URL:-$engine_url}" \
    -e EVAL_SERVICE_TRACKING_URI="${EVAL_SERVICE_TRACKING_URI:-$tracking_uri}" \
    -e EVAL_SERVICE_EXPERIMENT_NAME="$EVAL_SERVICE_EXPERIMENT_NAME" \
    -e EVAL_SERVICE_JUDGE_MODEL="$EVAL_SERVICE_JUDGE_MODEL" \
    -e EVAL_SERVICE_LOCK_DURATION_MS="${EVAL_SERVICE_LOCK_DURATION_MS:-600000}" \
    -e FLUXNOVA_USERNAME="${FLUXNOVA_USERNAME:-demo}" \
    -e FLUXNOVA_PASSWORD="${FLUXNOVA_PASSWORD:-demo}" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e OLLAMA_API_BASE="$OLLAMA_CONTAINER_URL" \
    -e LLM_JUDGE_PROVIDER="$LLM_JUDGE_PROVIDER" \
    "$IMAGE_NAME"
  finish_pod_creation
fi
echo "Worker started. Logs: podman logs -f eval-service-worker"
