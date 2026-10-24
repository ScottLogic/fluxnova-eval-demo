#!/usr/bin/env bash
# PGDATA stays in the VM's named volume; init.sh creates both application DBs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
POSTGRES_VOLUME="${POSTGRES_VOLUME:-postgres-local-data}"
POSTGRES_SUPERUSER="${POSTGRES_SUPERUSER:-postgres}"
podman volume create --ignore "$POSTGRES_VOLUME" >/dev/null
if ! start_existing_pod "$POSTGRES_POD_NAME" postgres; then
  ensure_image "${POSTGRES_IMAGE:-docker.io/library/postgres:16}"
  create_pod "$POSTGRES_POD_NAME" --network "$DEV_NETWORK" -p "${POSTGRES_PORT}:5432"
  run_container -d --pod "$POSTGRES_POD_NAME" --name postgres \
    -e POSTGRES_USER="$POSTGRES_SUPERUSER" \
    -e POSTGRES_PASSWORD="${POSTGRES_SUPERUSER_PASSWORD:-postgres}" \
    -e MLFLOW_POSTGRES_USER="${MLFLOW_POSTGRES_USER:-mlflow}" \
    -e MLFLOW_POSTGRES_PASSWORD="${MLFLOW_POSTGRES_PASSWORD:-mlflow}" \
    -e MLFLOW_POSTGRES_DB="${MLFLOW_POSTGRES_DB:-mlflow}" \
    -e FLUXNOVA_POSTGRES_USER="${FLUXNOVA_POSTGRES_USER:-fluxnova}" \
    -e FLUXNOVA_POSTGRES_PASSWORD="${FLUXNOVA_POSTGRES_PASSWORD:-fluxnova}" \
    -e FLUXNOVA_POSTGRES_DB="${FLUXNOVA_POSTGRES_DB:-fluxnova}" \
    -v "${POSTGRES_VOLUME}:/var/lib/postgresql/data" \
    -v "${LOCAL_DEV_DIR}/postgres:/docker-entrypoint-initdb.d:ro" \
    "${POSTGRES_IMAGE:-docker.io/library/postgres:16}"
  finish_pod_creation
fi
for ((i=0; i<90; i++)); do
  require_container_running postgres
  # The entrypoint's temporary initialization server is socket-only. Require TCP
  # so dependent services cannot race database/role creation on a fresh volume.
  if podman exec postgres pg_isready -h 127.0.0.1 -U "$POSTGRES_SUPERUSER" >/dev/null 2>&1; then
    echo "PostgreSQL ready: localhost:${POSTGRES_PORT} (internal ${POSTGRES_POD_NAME}:5432)"
    exit 0
  fi
  sleep 2
done
podman logs --tail 40 postgres >&2 || true
die 'PostgreSQL did not become ready. See podman logs postgres.'
