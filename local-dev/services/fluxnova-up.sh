#!/usr/bin/env bash
# Local development stack: Fluxnova + OTel Collector, run in a single Podman pod.
# Works from Git Bash on Windows too.
#
# The pod uses --network host (see OTEL-EXPORT-INVESTIGATION.md at the repo root): running
# Fluxnova in any isolated Podman network namespace — including this pod's own
# previously-bridge-networked namespace — silently breaks the OpenTelemetry Java SDK's OTLP
# exporter (traces/metrics never leave the JVM, no errors anywhere). Only the real host
# network namespace works. This means every address below is a plain "localhost" one (no
# port mapping happens or is needed — the pod's containers bind host ports directly), and
# sibling pods (mlflow-local, postgres-local) are reached via their own published host ports
# rather than by container/pod name, since a host-networked pod isn't attached to the
# fluxnova-dev bridge network aardvark-dns resolves those names on.
#
# default.yml's spring.datasource now points at PostgreSQL (postgres-local pod's
# "fluxnova" database) instead of the old H2 file default — run ./postgres-up.sh before
# this script.
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

# Shared config/data (.env, default.yml, otel-collector-config.yaml) lives in the parent
# local-dev directory — this script now sits in local-dev/services/.
LOCAL_DEV_DIR="$(cd .. && pwd)"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

FLUXNOVA_IMAGE="${FLUXNOVA_IMAGE:-fluxnova:local}"
# With --network host there's no port *mapping* — the container binds this port on the
# host directly, so it's passed through as SERVER_PORT for Spring Boot to actually bind
# rather than just labelling a `-p` mapping like before.
FLUXNOVA_PORT="${FLUXNOVA_PORT:-8080}"
OTEL_COLLECTOR_IMAGE="${OTEL_COLLECTOR_IMAGE:-docker.io/otel/opentelemetry-collector-contrib:0.160.0}"
# Fluxnova's PostgreSQL datasource credentials — read from .env (never hardcoded) and
# passed through as env vars for default.yml's ${VAR:default} placeholders to resolve
# (Spring Boot exposes container env vars directly to its property placeholder
# resolution). Must match what postgres-up.sh created the fluxnova role with.
FLUXNOVA_POSTGRES_USER="${FLUXNOVA_POSTGRES_USER:-fluxnova}"
FLUXNOVA_POSTGRES_PASSWORD="${FLUXNOVA_POSTGRES_PASSWORD:-fluxnova}"
FLUXNOVA_POSTGRES_DB="${FLUXNOVA_POSTGRES_DB:-fluxnova}"
# BPMN agent's OpenAI API key (only used while default.yml's spring.ai.model.chat is
# set to "openai") — read from .env, never hardcoded.
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
# The numeric MLflow experiment ID traces get sent to — MLflow's OTLP endpoint requires
# this on every request (see otel-collector-config.yaml). Must already exist; see
# local-dev/README.md for how to look it up. Left empty by default so this is opt-in.
MLFLOW_EXPERIMENT_ID="${MLFLOW_EXPERIMENT_ID:-}"
# Where the collector sends traces. This pod runs on --network host (see above), so
# mlflow-local's container-name DNS isn't reachable — address it via its published host
# port instead (mlflow-up.sh publishes ${MLFLOW_PORT:-5000}:5000). Override in .env if
# MLflow is on a different host port, or running as a separate host process.
MLFLOW_OTLP_ENDPOINT="${MLFLOW_OTLP_ENDPOINT:-http://localhost:${MLFLOW_PORT:-5000}}"

# Idempotent: if the pod already exists (e.g. this script was run before), just make
# sure it's started rather than failing on `podman pod create`/`podman run` name clashes.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' on --network host (fluxnova:${FLUXNOVA_PORT}, otel-collector:4317/4318, otel-metrics:8889 — all bound directly, no port mapping)..."
  # --network host means no -p port publishing (podman rejects combining the two) — the
  # containers bind these ports directly on the host. --add-host is harmless but no longer
  # load-bearing here (host.containers.internal is only needed by default.yml's Ollama
  # base-url; with host networking, localhost already reaches the host directly).
  podman pod create --name "$POD_NAME" \
    --network host \
    --add-host host.containers.internal:host-gateway

  echo "Starting otel-collector..."
  podman run -d --pod "$POD_NAME" --name otel-collector \
    -e MLFLOW_EXPERIMENT_ID="$MLFLOW_EXPERIMENT_ID" \
    -e MLFLOW_OTLP_ENDPOINT="$MLFLOW_OTLP_ENDPOINT" \
    -v "${LOCAL_DEV_DIR}/otel-collector-config.yaml:/etc/otelcol/config.yaml:ro" \
    "$OTEL_COLLECTOR_IMAGE" --config=/etc/otelcol/config.yaml

  echo "Starting fluxnova..."
  podman run -d --pod "$POD_NAME" --name fluxnova \
    -e SERVER_PORT="$FLUXNOVA_PORT" \
    -e OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
    -e OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
    -e FLUXNOVA_POSTGRES_USER="$FLUXNOVA_POSTGRES_USER" \
    -e FLUXNOVA_POSTGRES_PASSWORD="$FLUXNOVA_POSTGRES_PASSWORD" \
    -e FLUXNOVA_POSTGRES_DB="$FLUXNOVA_POSTGRES_DB" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -v "${LOCAL_DEV_DIR}/default.yml:/fluxnova/configuration/default.yml:ro" \
    "$FLUXNOVA_IMAGE"
fi

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
echo "OTel metrics:  localhost:8889/metrics  (Prometheus scrape endpoint — see observability-up.sh)"
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
