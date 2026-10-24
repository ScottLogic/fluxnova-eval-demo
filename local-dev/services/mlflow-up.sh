#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
MLFLOW_IMAGE="${MLFLOW_IMAGE:-ghcr.io/mlflow/mlflow:v3.16.0}"
MLFLOW_ARTIFACT_DIR="${MLFLOW_ARTIFACT_DIR:-${LOCAL_DEV_DIR}/.mlflow/artifacts}"
mkdir -p "$MLFLOW_ARTIFACT_DIR"
ARTIFACT_DIR_RESOLVED="$(cd "$MLFLOW_ARTIFACT_DIR" && { pwd -W 2>/dev/null || pwd; })"
MLFLOW_BACKEND_STORE_URI="${MLFLOW_BACKEND_STORE_URI:-postgresql://${MLFLOW_POSTGRES_USER:-mlflow}:${MLFLOW_POSTGRES_PASSWORD:-mlflow}@${POSTGRES_POD_NAME}:5432/${MLFLOW_POSTGRES_DB:-mlflow}}"
podman volume create --ignore "$MLFLOW_RUNTIME_VOLUME" >/dev/null
if ! start_existing_pod "$MLFLOW_POD_NAME" mlflow; then
  podman pod create --name "$MLFLOW_POD_NAME" --network "$DEV_NETWORK" -p "${MLFLOW_PORT}:5000" >/dev/null
  podman run -d --pod "$MLFLOW_POD_NAME" --name mlflow \
    -e MLFLOW_BACKEND_STORE_URI="$MLFLOW_BACKEND_STORE_URI" \
    -e EVAL_SERVICE_EXPERIMENT_NAME="$EVAL_SERVICE_EXPERIMENT_NAME" \
    -v "${ARTIFACT_DIR_RESOLVED}:/mlflow-artifacts" \
    -v "${MLFLOW_RUNTIME_VOLUME}:/mlflow-runtime" \
    -v "${LOCAL_DEV_DIR}/mlflow:/local-dev-mlflow:ro" \
    --entrypoint sh "$MLFLOW_IMAGE" /local-dev-mlflow/start.sh
fi
require_http "http://localhost:${MLFLOW_PORT}/version" mlflow
for ((i=0; i<90; i++)); do
  if podman exec mlflow test -s /mlflow-runtime/headers.yaml; then break; fi
  sleep 2
done
podman exec mlflow test -s /mlflow-runtime/headers.yaml || die 'MLflow experiment initialization failed; see podman logs mlflow.'
echo "MLflow: ${READY_URL%/version}"
echo "Trace experiment: $EVAL_SERVICE_EXPERIMENT_NAME (ID resolved automatically)"
if [ "${MLFLOW_OPEN_BROWSER:-true}" = true ]; then open_browser "${READY_URL%/version}"; fi
