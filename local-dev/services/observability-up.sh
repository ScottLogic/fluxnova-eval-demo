#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
POD_NAME="${OBSERVABILITY_POD_NAME:-observability-local}"
if [ "$DEV_NETWORK_MODE" = host ]; then
  network_args=(--network host)
  prometheus_listen="$PROMETHEUS_PORT"
  grafana_listen="$GRAFANA_PORT"
  config="$LOCAL_DEV_DIR/prometheus-host.yml"
else
  network_args=(--network "$DEV_NETWORK" -p "${PROMETHEUS_PORT}:9090" -p "${GRAFANA_PORT}:3000")
  prometheus_listen=9090
  grafana_listen=3000
  config="$LOCAL_DEV_DIR/prometheus.yml"
fi
if ! start_existing_pod "$POD_NAME" prometheus grafana; then
  ensure_image "${PROMETHEUS_IMAGE:-docker.io/prom/prometheus:v3.14.0}"
  ensure_image "${GRAFANA_IMAGE:-docker.io/grafana/grafana:13.2.1}"
  create_pod "$POD_NAME" "${network_args[@]}"
  run_container -d --pod "$POD_NAME" --name prometheus \
    -v "${PROMETHEUS_CONFIG_FILE:-$config}:/etc/prometheus/prometheus.yml:ro" \
    "${PROMETHEUS_IMAGE:-docker.io/prom/prometheus:v3.14.0}" \
    --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus \
    --web.listen-address=":${prometheus_listen}"
  run_container -d --pod "$POD_NAME" --name grafana \
    -e GF_SERVER_HTTP_PORT="$grafana_listen" \
    -e PROMETHEUS_URL="http://localhost:${prometheus_listen}" \
    -e GF_SECURITY_ADMIN_USER=admin -e GF_SECURITY_ADMIN_PASSWORD=admin \
    -e GF_AUTH_ANONYMOUS_ENABLED=true -e GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
    -e GF_USERS_DEFAULT_THEME=light \
    -v "${LOCAL_DEV_DIR}/grafana/provisioning:/etc/grafana/provisioning:ro" \
    -v "${LOCAL_DEV_DIR}/grafana/dashboards:/var/lib/grafana/dashboards:ro" \
    "${GRAFANA_IMAGE:-docker.io/grafana/grafana:13.2.1}"
  finish_pod_creation
fi
require_http "http://localhost:${PROMETHEUS_PORT}/-/ready" prometheus
require_http "http://localhost:${GRAFANA_PORT}/api/health" grafana
echo "Grafana: ${READY_URL%/api/health} (Fluxnova > Fluxnova GenAI Metrics)"
echo "Prometheus: http://localhost:${PROMETHEUS_PORT}/targets"
if [ "${OBSERVABILITY_OPEN_BROWSER:-true}" = true ]; then open_browser "${READY_URL%/api/health}/d/fluxnova-genai"; fi
