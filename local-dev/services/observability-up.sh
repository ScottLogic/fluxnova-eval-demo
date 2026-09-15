#!/usr/bin/env bash
# Local development observability stack: Prometheus + Grafana, run in a single Podman pod
# (observability-local) — separate from fluxnova-local so it can be started/stopped
# independently. Works from Git Bash on Windows too.
#
# Data flow (see the main README's "GenAI observability" section):
#   Fluxnova --OTLP--> OTel Collector (fluxnova-local :8889 Prometheus exporter)
#            --scrape--> Prometheus (this pod :9090) --query--> Grafana (this pod :3000)
#
# This pod runs on --network host, same as fluxnova-local — see
# OTEL-EXPORT-INVESTIGATION.md at the repo root. That doc's fix was originally just for
# Fluxnova (running it in any isolated Podman network namespace silently breaks the
# OpenTelemetry Java SDK's OTLP export), but Prometheus scraping fluxnova-local's :8889
# from a *different* namespace turned out to hit a second, separate problem: on Podman
# Desktop/machine (Windows), host.containers.internal routes out to the actual Windows
# host, not back into the podman-machine VM where a --network host pod's ports actually
# live — so it times out (and the bridge network's own gateway IP gets connection
# refused). Confirmed empirically: a throwaway --network host container CAN reach
# another --network host container via plain localhost; a bridge-networked one cannot,
# by either address. Hence this pod is host-networked too, and reaches the OTel
# Collector via localhost:8889 like Fluxnova does (see prometheus.yml) — no `-p`
# publishing happens or is needed (`podman pod create --network host` rejects `-p`).
# Both containers here still share one network namespace, so Grafana reaches Prometheus
# via localhost:9090 (see grafana/provisioning/datasources/prometheus.yml).
# Requires fluxnova-up.sh already running for metrics to appear (Prometheus will just
# report the target down until then).
#
# Grafana starts with the Prometheus datasource and the "Fluxnova GenAI Metrics"
# dashboard already provisioned (grafana/dashboards/gen-ai.json), and anonymous access
# enabled so you can view dashboards without logging in (admin login is still
# admin/admin for editing).
#
# Usage (from this directory):
#   ./observability-up.sh
#   ./observability-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Prevent Git Bash/MSYS from mangling container-side paths in -v arguments.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

POD_NAME="${OBSERVABILITY_POD_NAME:-observability-local}"

# Shared config (.env, prometheus.yml, grafana/) lives in the parent local-dev
# directory — this script sits in local-dev/services/.
LOCAL_DEV_DIR="$(cd .. && pwd)"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-docker.io/prom/prometheus:v3.14.0}"
GRAFANA_IMAGE="${GRAFANA_IMAGE:-docker.io/grafana/grafana:13.2.1}"
# With --network host there's no port *mapping* — these bind directly on the host, so
# they're passed through as listen-address/port config rather than just labelling a `-p`.
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"

# Idempotent: if the pod already exists, just make sure it's started rather than failing
# on `podman pod create`/`podman run` name clashes.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' on --network host (prometheus:${PROMETHEUS_PORT}, grafana:${GRAFANA_PORT} — bound directly, no port mapping)..."
  podman pod create --name "$POD_NAME" --network host

  echo "Starting prometheus..."
  podman run -d --pod "$POD_NAME" --name prometheus \
    -v "${LOCAL_DEV_DIR}/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
    "$PROMETHEUS_IMAGE" \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/prometheus \
    --web.enable-lifecycle \
    --web.listen-address=":${PROMETHEUS_PORT}"

  echo "Starting grafana..."
  podman run -d --pod "$POD_NAME" --name grafana \
    -e GF_SERVER_HTTP_PORT="$GRAFANA_PORT" \
    -e GF_SECURITY_ADMIN_USER=admin \
    -e GF_SECURITY_ADMIN_PASSWORD=admin \
    -e GF_AUTH_ANONYMOUS_ENABLED=true \
    -e GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
    -e GF_USERS_DEFAULT_THEME=light \
    -v "${LOCAL_DEV_DIR}/grafana/provisioning:/etc/grafana/provisioning:ro" \
    -v "${LOCAL_DEV_DIR}/grafana/dashboards:/var/lib/grafana/dashboards:ro" \
    "$GRAFANA_IMAGE"
fi

# Wait for Grafana to become reachable via localhost, then fall back to the Podman
# machine's own IP if it isn't — see README.md's "Troubleshooting" section for why
# localhost can be unreachable on some Windows/WSL2 setups even though the container is
# running fine.
wait_for_grafana() {
  local url="$1" tries="${2:-30}"
  for ((i = 0; i < tries; i++)); do
    if curl -sf -o /dev/null --max-time 2 "$url/api/health"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "Waiting for Grafana to become ready..."
GRAFANA_URL="http://localhost:${GRAFANA_PORT}"
PROMETHEUS_URL="http://localhost:${PROMETHEUS_PORT}"
if ! wait_for_grafana "$GRAFANA_URL"; then
  WSL_IP=""
  if command -v wsl.exe >/dev/null 2>&1; then
    WSL_IP="$(wsl.exe -d podman-machine-default -- ip -4 addr show eth0 2>/dev/null \
      | grep -oP 'inet \K[\d.]+' || true)"
  fi
  if [ -n "$WSL_IP" ] && wait_for_grafana "http://${WSL_IP}:${GRAFANA_PORT}" 10; then
    echo "localhost:${GRAFANA_PORT} isn't reachable on this machine (known WSL2 issue — see" \
      "README.md's Troubleshooting section); using the Podman machine's IP instead."
    GRAFANA_URL="http://${WSL_IP}:${GRAFANA_PORT}"
    PROMETHEUS_URL="http://${WSL_IP}:${PROMETHEUS_PORT}"
  else
    echo "Warning: Grafana doesn't seem to be responding yet on localhost or the Podman" \
      "machine's IP. It may just need more time — check 'podman logs -f grafana'." >&2
  fi
fi

echo
echo "Grafana UI:    ${GRAFANA_URL}   (dashboard: Fluxnova > Fluxnova GenAI Metrics; login admin/admin to edit)"
echo "Prometheus:    ${PROMETHEUS_URL}   (targets: ${PROMETHEUS_URL}/targets — localhost:8889 should be UP)"
echo "Logs:          podman pod logs -f $POD_NAME   (or: podman logs -f grafana / prometheus)"
echo "Stop/remove:   ./observability-down.sh"

# Open Grafana in the default browser — set OBSERVABILITY_OPEN_BROWSER=false to skip.
if [ "${OBSERVABILITY_OPEN_BROWSER:-true}" = "true" ]; then
  GRAFANA_DASH_URL="${GRAFANA_URL}/d/fluxnova-genai"
  if command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "$GRAFANA_DASH_URL" >/dev/null 2>&1 || true   # Windows / Git Bash
  elif command -v open >/dev/null 2>&1; then
    open "$GRAFANA_DASH_URL" || true                            # macOS
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$GRAFANA_DASH_URL" >/dev/null 2>&1 || true         # Linux
  fi
fi
