#!/usr/bin/env bash
# MLflow tracking server, run as its own single-container Podman pod — separate from
# fluxnova-local (see fluxnova-up.sh) so it can be started/stopped independently (it's a
# long-lived dev service, not tied to any one Fluxnova run).
#
# This replaces the host-run `mlflow server ...` process described in the main README's
# "Running the MLflow tracking server" section with a container, backed by the *same*
# PostgreSQL database (postgres-local's "mlflow" database — see postgres-up.sh) so
# `mlflow-eval` (run on the host) and this container see identical data. Requires
# postgres-up.sh to already be running.
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

# Shared config/data (.env, artifact dir) lives in / is resolved relative to the parent
# local-dev directory — this script now sits in local-dev/services/.
LOCAL_DEV_DIR="$(cd .. && pwd)"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

MLFLOW_IMAGE="${MLFLOW_IMAGE:-ghcr.io/mlflow/mlflow:v3.15.2}"
MLFLOW_PORT="${MLFLOW_PORT:-5000}"
# Backend store is now PostgreSQL (postgres-local's mlflow database, created by
# postgres-up.sh's postgres/init.sh) instead of the old SQLite file. Artifacts
# (e.g. logged models/files) still live on a bind-mounted host directory since Postgres
# only stores metadata, not blobs. Credentials come entirely from .env (never
# hardcoded) — must match what postgres-up.sh created the mlflow role with.
POSTGRES_HOST="${POSTGRES_POD_NAME:-postgres-local}"
# NOTE: this is the container's *internal* port (always 5432, per postgres-up.sh's
# `-p "${POSTGRES_PORT}:5432"`), not POSTGRES_PORT — that env var is only the
# host-published port and has no bearing on pod-to-pod traffic, which always targets
# 5432 inside the postgres-local pod. Reusing POSTGRES_PORT here would break this
# pod's connection to Postgres whenever POSTGRES_PORT is overridden (e.g. to avoid a
# host port collision) — see default.yml's fluxnova datasource URL for the same
# hardcoded-5432 pattern.
POSTGRES_CONTAINER_PORT=5432
MLFLOW_POSTGRES_USER="${MLFLOW_POSTGRES_USER:-mlflow}"
MLFLOW_POSTGRES_PASSWORD="${MLFLOW_POSTGRES_PASSWORD:-mlflow}"
MLFLOW_POSTGRES_DB="${MLFLOW_POSTGRES_DB:-mlflow}"
MLFLOW_BACKEND_STORE_URI="${MLFLOW_BACKEND_STORE_URI:-postgresql://${MLFLOW_POSTGRES_USER}:${MLFLOW_POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_CONTAINER_PORT}/${MLFLOW_POSTGRES_DB}}"
MLFLOW_ARTIFACT_DIR="${MLFLOW_ARTIFACT_DIR:-${LOCAL_DEV_DIR}/../harness/.mlflow/artifacts}"
mkdir -p "$MLFLOW_ARTIFACT_DIR"
ARTIFACT_DIR_RESOLVED="$(cd "$MLFLOW_ARTIFACT_DIR" && pwd)"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"

# Same shared network as fluxnova-up.sh's fluxnova-local pod and postgres-up.sh's
# postgres-local pod, so this pod can reach Postgres by pod name and the OTel Collector
# can reach this pod by pod name (`mlflow-local`) — see fluxnova-up.sh for why
# host.containers.internal doesn't work for pod-to-pod traffic on this machine.
podman network create --ignore "$DEV_NETWORK"


# Idempotent: if the pod already exists (e.g. this script was run before), just make
# sure it's started rather than failing on `podman pod create`/`podman run` name clashes.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' (mlflow:${MLFLOW_PORT}->5000)..."
  # --add-host lets this pod's containers (e.g. an AI Gateway endpoint pointed at a
  # host-run Ollama) reach the host via host.containers.internal — same as fluxnova-up.sh.
  podman pod create --name "$POD_NAME" \
    -p "${MLFLOW_PORT}:5000" \
    --network "$DEV_NETWORK" \
    --add-host host.containers.internal:host-gateway

  echo "Starting mlflow..."
  podman run -d --pod "$POD_NAME" --name mlflow \
    -v "${ARTIFACT_DIR_RESOLVED}:/mlflow-artifacts" \
    --entrypoint sh \
    "$MLFLOW_IMAGE" \
    -c "pip install --quiet psycopg2-binary && mlflow server \
      --backend-store-uri '${MLFLOW_BACKEND_STORE_URI}' \
      --default-artifact-root /mlflow-artifacts \
      --host 0.0.0.0 --port 5000 --allowed-hosts '*' --cors-allowed-origins '*'"
fi

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
echo "Backend store: postgresql://${MLFLOW_POSTGRES_USER}:***@${POSTGRES_HOST}:${POSTGRES_CONTAINER_PORT}/${MLFLOW_POSTGRES_DB}"
echo "Artifacts:     ${ARTIFACT_DIR_RESOLVED}"
echo "Logs:          podman logs -f mlflow"
echo "Stop/remove:   ./mlflow-down.sh"

# Open the UI in the default browser — set MLFLOW_OPEN_BROWSER=false to skip.
if [ "${MLFLOW_OPEN_BROWSER:-true}" = "true" ]; then
  if command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "$MLFLOW_URL" >/dev/null 2>&1 || true   # Windows / Git Bash
  fi
fi
