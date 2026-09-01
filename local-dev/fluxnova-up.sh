#!/usr/bin/env bash
# Local development stack: Fluxnova + OTel Collector, run in a single Podman pod.
# Works from Git Bash on Windows too.
#
# All containers in a pod share one network namespace, so they talk to each other via
# `localhost` rather than by service name — that's why default.yml points
# exporterEndpoint at http://localhost:4317 instead of http://otel-collector:4317.
#
# Usage (from this directory):
#   ./fluxnova-up.sh
#   ./fluxnova-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Prevent Git Bash/MSYS from mangling container-side paths (e.g. /etc/otelcol/config.yaml)
# in -v/--add-host arguments by rewriting them as Windows paths.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

POD_NAME="${POD_NAME:-fluxnova-local}"

# Load .env (KEY=VALUE lines) if present.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

FLUXNOVA_IMAGE="${FLUXNOVA_IMAGE:-fluxnova:local}"
FLUXNOVA_PORT="${FLUXNOVA_PORT:-8080}"
OTEL_COLLECTOR_IMAGE="${OTEL_COLLECTOR_IMAGE:-docker.io/otel/opentelemetry-collector-contrib:latest}"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"
# The numeric MLflow experiment ID traces get sent to — MLflow's OTLP endpoint requires
# this on every request (see otel-collector-config.yaml). Must already exist; see
# local-dev/README.md for how to look it up. Left empty by default so this is opt-in.
MLFLOW_EXPERIMENT_ID="${MLFLOW_EXPERIMENT_ID:-}"
# Where the collector sends traces — defaults to the mlflow-local pod (mlflow-up.sh)
# on the shared fluxnova-dev network; override in .env if running MLflow as a host
# process instead (http://host.containers.internal:5000).
MLFLOW_OTLP_ENDPOINT="${MLFLOW_OTLP_ENDPOINT:-http://mlflow-local:5000}"

# Shared user-defined network so this pod can reach the mlflow-local pod (see
# mlflow-up.sh) by container name — sibling pods don't share a network namespace,
# and routing through host.containers.internal doesn't work for pod-to-pod traffic on
# this machine (it resolves to the gateway *out* of the Podman VM, not back into it).
podman network create --ignore "$DEV_NETWORK"

echo "Creating pod '$POD_NAME' (fluxnova:${FLUXNOVA_PORT}->8080, otel-collector:4317/4318)..."
# --add-host must be set at pod level (not per-container) since networking is shared.
podman pod create --name "$POD_NAME" \
  -p "${FLUXNOVA_PORT}:8080" \
  -p 4317:4317 \
  -p 4318:4318 \
  --network "$DEV_NETWORK" \
  --add-host host.containers.internal:host-gateway

echo "Starting otel-collector..."
podman run -d --pod "$POD_NAME" --name otel-collector \
  -e MLFLOW_EXPERIMENT_ID="$MLFLOW_EXPERIMENT_ID" \
  -e MLFLOW_OTLP_ENDPOINT="$MLFLOW_OTLP_ENDPOINT" \
  -v "$(pwd)/otel-collector-config.yaml:/etc/otelcol/config.yaml:ro" \
  "$OTEL_COLLECTOR_IMAGE" --config=/etc/otelcol/config.yaml

echo "Starting fluxnova..."
podman run -d --pod "$POD_NAME" --name fluxnova \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
  -e OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
  -v "$(pwd)/default.yml:/fluxnova/configuration/default.yml:ro" \
  "$FLUXNOVA_IMAGE"

# Wait for Fluxnova to become reachable via localhost, then fall back to the Podman
# machine's own IP if it isn't — see mlflow-up.sh / README.md's "Troubleshooting"
# section for why localhost can be unreachable on some Windows/WSL2 setups even though
# the container is running fine (not observed for Fluxnova/Tomcat so far, but the same
# fallback is applied here for consistency/safety).
wait_for_fluxnova() {
  local url="$1" tries="${2:-60}"
  for ((i = 0; i < tries; i++)); do
    if curl -sf -o /dev/null --max-time 2 "$url/engine-rest/engine"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

echo "Waiting for Fluxnova to become ready..."
FLUXNOVA_URL="http://localhost:${FLUXNOVA_PORT}"
if ! wait_for_fluxnova "$FLUXNOVA_URL"; then
  WSL_IP=""
  if command -v wsl.exe >/dev/null 2>&1; then
    WSL_IP="$(wsl.exe -d podman-machine-default -- ip -4 addr show eth0 2>/dev/null \
      | grep -oP 'inet \K[\d.]+' || true)"
  fi
  if [ -n "$WSL_IP" ] && wait_for_fluxnova "http://${WSL_IP}:${FLUXNOVA_PORT}" 10; then
    echo "localhost:${FLUXNOVA_PORT} isn't reachable on this machine (see README.md's" \
      "Troubleshooting section); using the Podman machine's IP instead."
    FLUXNOVA_URL="http://${WSL_IP}:${FLUXNOVA_PORT}"
  else
    echo "Warning: Fluxnova doesn't seem to be responding yet on localhost or the Podman" \
      "machine's IP. It may just need more time — check 'podman logs -f fluxnova'." >&2
  fi
fi

echo
echo "Fluxnova:      ${FLUXNOVA_URL}/engine-rest"
echo "Fluxnova UI:   ${FLUXNOVA_URL}/fluxnova-welcome/index.html"
echo "OTel gRPC:     localhost:4317"
echo "OTel HTTP:     localhost:4318"
echo "Logs:          podman pod logs -f $POD_NAME   (or: podman logs -f fluxnova / otel-collector)"
echo "Stop/remove:   ./fluxnova-down.sh"

# Open the UI in the default browser — set FLUXNOVA_OPEN_BROWSER=false to skip.
if [ "${FLUXNOVA_OPEN_BROWSER:-true}" = "true" ]; then
  FLUXNOVA_UI_URL="${FLUXNOVA_URL}/fluxnova-welcome/index.html"
  if command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "$FLUXNOVA_UI_URL" >/dev/null 2>&1 || true   # Windows / Git Bash
  elif command -v open >/dev/null 2>&1; then
    open "$FLUXNOVA_UI_URL" || true                            # macOS
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FLUXNOVA_UI_URL" >/dev/null 2>&1 || true         # Linux
  fi
fi
