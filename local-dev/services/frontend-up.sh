#!/usr/bin/env bash
# nginx and ui-api share a namespace; bridge mode uses internal dependency URLs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
POD_NAME="${FRONTEND_POD_NAME:-frontend-local}"
FRONTEND_IMAGE_NAME="${FRONTEND_IMAGE:-frontend:local}"
UI_API_IMAGE_NAME="${UI_API_IMAGE:-ui-api:local}"
FRONTEND_PORT="${FRONTEND_PORT:-8081}"
UI_API_PORT="${UI_API_PORT:-8090}"
require_http "http://localhost:${FLUXNOVA_PORT}/engine-rest/engine" fluxnova
if [ "$DEV_NETWORK_MODE" = host ]; then
  network_args=(--network host)
  frontend_listen="$FRONTEND_PORT"
  api_listen="$UI_API_PORT"
  engine_url="http://localhost:${FLUXNOVA_PORT}/engine-rest"
  tracking_url="http://localhost:${MLFLOW_PORT}"
  listener_url="http://localhost:${EVAL_LISTENER_CONTROL_PORT:-8092}"
else
  network_args=(--network "$DEV_NETWORK" -p "${FRONTEND_PORT}:80" -p "${UI_API_PORT}:8090")
  frontend_listen=80
  api_listen=8090
  engine_url="http://${FLUXNOVA_POD_NAME}:8080/engine-rest"
  tracking_url="http://${MLFLOW_POD_NAME}:5000"
  listener_url="http://${EVAL_LISTENER_POD_NAME:-eval-listener-local}:8092"
fi
if ! start_existing_pod "$POD_NAME" ui-api frontend; then
  if [ "${REBUILD:-}" = 1 ] || ! podman image exists "$FRONTEND_IMAGE_NAME"; then
    ensure_image docker.io/library/node:22-slim
    ensure_image docker.io/library/nginx:1.29-alpine
    podman build --pull=never -f "$REPO_ROOT/frontend/Dockerfile" -t "$FRONTEND_IMAGE_NAME" "$REPO_ROOT"
  fi
  if [ "${REBUILD:-}" = 1 ] || ! podman image exists "$UI_API_IMAGE_NAME"; then
    ensure_image docker.io/library/python:3.11-slim
    podman build --pull=never -f "$REPO_ROOT/ui-api/Dockerfile" -t "$UI_API_IMAGE_NAME" "$REPO_ROOT"
  fi
  create_pod "$POD_NAME" "${network_args[@]}"
  run_container -d --pod "$POD_NAME" --name ui-api \
    -e MLFLOW_DISABLE_TELEMETRY=true \
    -e UI_API_PORT="$api_listen" \
    -e FLUXNOVA_URL="${UI_API_FLUXNOVA_URL:-$engine_url}" \
    -e MLFLOW_TRACKING_URI="${UI_API_TRACKING_URI:-$tracking_url}" \
    -e MLFLOW_EXPERIMENT_NAME="${MLFLOW_EXPERIMENT_NAME:-$EVAL_SERVICE_EXPERIMENT_NAME}" \
    -e EVAL_SERVICE_EXPERIMENT_NAME="$EVAL_SERVICE_EXPERIMENT_NAME" \
    -e UI_API_EVAL_LISTENER_URL="${UI_API_EVAL_LISTENER_URL:-$listener_url}" \
    -e FLUXNOVA_USERNAME="${FLUXNOVA_USERNAME:-demo}" \
    -e FLUXNOVA_PASSWORD="${FLUXNOVA_PASSWORD:-demo}" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e LLM_JUDGE_PROVIDER="$LLM_JUDGE_PROVIDER" \
    -e DECISION_QUALITY_MODEL="$DECISION_QUALITY_MODEL" \
    -e OLLAMA_API_BASE="$OLLAMA_CONTAINER_URL" \
    "$UI_API_IMAGE_NAME"
  run_container -d --pod "$POD_NAME" --name frontend \
    -e API_PROXY_PASS="${FRONTEND_API_PROXY_PASS:-http://localhost:${api_listen}}" \
    -e LISTEN_PORT="$frontend_listen" \
    "$FRONTEND_IMAGE_NAME"
  finish_pod_creation
fi
require_http "http://localhost:${FRONTEND_PORT}/" frontend
require_http "http://localhost:${UI_API_PORT}/health" ui-api
echo "Frontend UI: http://localhost:${FRONTEND_PORT}"
echo "ui-api: http://localhost:${UI_API_PORT} (also proxied at /api/)"
if [ "${FRONTEND_OPEN_BROWSER:-true}" = true ]; then open_browser "http://localhost:${FRONTEND_PORT}"; fi
