#!/usr/bin/env bash
# Fluxnova + collector share a pod namespace; published ports reach the Mac/Windows host.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
FLUXNOVA_IMAGE="${FLUXNOVA_IMAGE:-ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.2.0}"
# Current published engine image is AMD64-only. Other images remain native ARM64.
FLUXNOVA_PLATFORM="${FLUXNOVA_PLATFORM:-linux/amd64}"
OTEL_COLLECTOR_IMAGE="${OTEL_COLLECTOR_IMAGE:-docker.io/otel/opentelemetry-collector-contrib:0.160.0}"

require_http "http://localhost:${MLFLOW_PORT}/version" mlflow
podman exec mlflow test -s /mlflow-runtime/headers.yaml || die 'Restart MLflow with mlflow-up.sh to initialize the trace experiment.'
if [ "$DEV_NETWORK_MODE" = host ]; then
  network_args=(--network host)
  engine_port="$FLUXNOVA_PORT"
  db_host=localhost
  db_port="$POSTGRES_PORT"
  mlflow_endpoint="http://localhost:${MLFLOW_PORT}"
else
  network_args=(--network "$DEV_NETWORK" -p "${FLUXNOVA_PORT}:8080" -p "${OTEL_GRPC_PORT}:4317" -p "${OTEL_HTTP_PORT}:4318" -p "${OTEL_METRICS_PORT}:8889")
  engine_port=8080
  db_host="$POSTGRES_POD_NAME"
  db_port=5432
  mlflow_endpoint="http://${MLFLOW_POD_NAME}:5000"
fi

if ! start_existing_pod "$FLUXNOVA_POD_NAME" fluxnova otel-collector; then
  podman pod create --name "$FLUXNOVA_POD_NAME" "${network_args[@]}" >/dev/null
  podman run -d --pod "$FLUXNOVA_POD_NAME" --name otel-collector \
    -e MLFLOW_OTLP_ENDPOINT="${MLFLOW_OTLP_ENDPOINT:-$mlflow_endpoint}" \
    -v "${MLFLOW_RUNTIME_VOLUME}:/mlflow-runtime:ro" \
    -v "${LOCAL_DEV_DIR}/otel-collector-config.yaml:/etc/otelcol/config.yaml:ro" \
    "$OTEL_COLLECTOR_IMAGE" --config=/etc/otelcol/config.yaml
  podman run -d --pod "$FLUXNOVA_POD_NAME" --name fluxnova --platform "$FLUXNOVA_PLATFORM" \
    -e SERVER_PORT="$engine_port" \
    -e FLUXNOVA_POSTGRES_HOST="${FLUXNOVA_POSTGRES_HOST:-$db_host}" \
    -e FLUXNOVA_POSTGRES_PORT="${FLUXNOVA_POSTGRES_PORT:-$db_port}" \
    -e FLUXNOVA_POSTGRES_USER="${FLUXNOVA_POSTGRES_USER:-fluxnova}" \
    -e FLUXNOVA_POSTGRES_PASSWORD="${FLUXNOVA_POSTGRES_PASSWORD:-fluxnova}" \
    -e FLUXNOVA_POSTGRES_DB="${FLUXNOVA_POSTGRES_DB:-fluxnova}" \
    -e SPRING_AI_OLLAMA_BASE_URL="$OLLAMA_CONTAINER_URL" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
    -e OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
    -v "${LOCAL_DEV_DIR}/default.yml:/fluxnova/configuration/default.yml:ro" \
    "$FLUXNOVA_IMAGE"
fi
require_http "http://localhost:${FLUXNOVA_PORT}/engine-rest/engine" fluxnova
FLUXNOVA_URL="${READY_URL%/engine-rest/engine}"
echo "Fluxnova REST: ${FLUXNOVA_URL}/engine-rest"
echo "Collector metrics: http://localhost:${OTEL_METRICS_PORT}/metrics (bridge mode)"
if [ "${FLUXNOVA_OPEN_BROWSER:-true}" = true ]; then open_browser "${FLUXNOVA_URL}/fluxnova-welcome/index.html"; fi
