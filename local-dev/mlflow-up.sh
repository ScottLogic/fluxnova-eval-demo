#!/usr/bin/env bash
# MLflow tracking server, run as its own single-container Podman pod — separate from
# fluxnova-local (see fluxnova-up.sh) so it can be started/stopped independently (it's a
# long-lived dev service, not tied to any one Fluxnova run).
#
# This replaces the host-run `mlflow server ...` process described in the main README's
# "Running the MLflow tracking server" section with a container, backed by the *same*
# SQLite file (harness/.mlflow/mlflow.db) so `mlflow-eval` (run on the host) and this
# container see identical data.
#
# Usage (from this directory):
#   ./mlflow-up.sh
#   ./mlflow-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Prevent Git Bash/MSYS from mangling container-side paths in -v arguments.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

POD_NAME="${MLFLOW_POD_NAME:-mlflow-local}"

# Load .env (KEY=VALUE lines) if present.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

MLFLOW_IMAGE="${MLFLOW_IMAGE:-ghcr.io/mlflow/mlflow:latest}"
MLFLOW_PORT="${MLFLOW_PORT:-5000}"
# Where the SQLite backend store lives on the host — defaults to the same path the
# harness/README already use (harness/.mlflow/mlflow.db), so this container and any
# host-run `mlflow-eval` / `mlflow ui` commands share one database.
MLFLOW_BACKEND_STORE_DIR="${MLFLOW_BACKEND_STORE_DIR:-../harness/.mlflow}"
mkdir -p "$MLFLOW_BACKEND_STORE_DIR"
BACKEND_STORE_DIR_RESOLVED="$(cd "$MLFLOW_BACKEND_STORE_DIR" && pwd)"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"

# Same shared network as fluxnova-up.sh's fluxnova-local pod, so the OTel Collector there can
# reach this pod by container name (`mlflow`) — see fluxnova-up.sh for why host.containers.internal
# doesn't work for pod-to-pod traffic on this machine.
podman network create --ignore "$DEV_NETWORK"

echo "Creating pod '$POD_NAME' (mlflow:${MLFLOW_PORT}->5000)..."
# --add-host lets this pod's containers (e.g. an AI Gateway endpoint pointed at a
# host-run Ollama) reach the host via host.containers.internal — same as fluxnova-up.sh.
podman pod create --name "$POD_NAME" \
  -p "${MLFLOW_PORT}:5000" \
  --network "$DEV_NETWORK" \
  --add-host host.containers.internal:host-gateway

echo "Starting mlflow..."
podman run -d --pod "$POD_NAME" --name mlflow \
  -v "${BACKEND_STORE_DIR_RESOLVED}:/mlflow-data" \
  "$MLFLOW_IMAGE" \
  mlflow server --backend-store-uri sqlite:////mlflow-data/mlflow.db --host 0.0.0.0 --port 5000 \
    --allowed-hosts "*" --cors-allowed-origins "*"

# Wait for MLflow to become reachable via localhost, then fall back to the Podman
# machine's own IP if it isn't — see the "Troubleshooting" section in README.md for why
# localhost can be unreachable on some Windows/WSL2 setups even though the container is
# running fine.
wait_for_mlflow() {
  local url="$1" tries="${2:-30}"
  for ((i = 0; i < tries; i++)); do
    if curl -sf -o /dev/null --max-time 2 "$url/version"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "Waiting for MLflow to become ready..."
MLFLOW_URL="http://localhost:${MLFLOW_PORT}"
if ! wait_for_mlflow "$MLFLOW_URL"; then
  WSL_IP=""
  if command -v wsl.exe >/dev/null 2>&1; then
    WSL_IP="$(wsl.exe -d podman-machine-default -- ip -4 addr show eth0 2>/dev/null \
      | grep -oP 'inet \K[\d.]+' || true)"
  fi
  if [ -n "$WSL_IP" ] && wait_for_mlflow "http://${WSL_IP}:${MLFLOW_PORT}" 10; then
    echo "localhost:${MLFLOW_PORT} isn't reachable on this machine (known WSL2 issue — see" \
      "README.md's Troubleshooting section); using the Podman machine's IP instead."
    MLFLOW_URL="http://${WSL_IP}:${MLFLOW_PORT}"
  else
    echo "Warning: MLflow doesn't seem to be responding yet on localhost or the Podman" \
      "machine's IP. It may just need more time — check 'podman logs -f mlflow'." >&2
  fi
fi

echo
echo "MLflow UI:     ${MLFLOW_URL}"
echo "OTLP traces:   ${MLFLOW_URL}/v1/traces (point the OTel Collector's otlphttp exporter here)"
echo "Backend store: ${BACKEND_STORE_DIR_RESOLVED}/mlflow.db"
echo "Logs:          podman logs -f mlflow"
echo "Stop/remove:   ./mlflow-down.sh"

# Open the UI in the default browser — set MLFLOW_OPEN_BROWSER=false to skip.
if [ "${MLFLOW_OPEN_BROWSER:-true}" = "true" ]; then
  if command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "$MLFLOW_URL" >/dev/null 2>&1 || true   # Windows / Git Bash
  fi
fi
