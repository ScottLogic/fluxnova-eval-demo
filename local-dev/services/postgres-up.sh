#!/usr/bin/env bash
# PostgreSQL database server, run as its own single-container Podman pod — the same
# pattern as mlflow-up.sh/fluxnova-up.sh, kept separate since it's a long-lived dev
# service shared by both MLflow (backend store) and Fluxnova (process-engine
# datasource), replacing their respective SQLite and H2 file-based defaults.
#
# On first startup it runs postgres/init.sh, which creates two databases/roles
# from env vars (set in .env, never hardcoded):
#   - $MLFLOW_POSTGRES_DB/$MLFLOW_POSTGRES_USER     — used by mlflow-up.sh's --backend-store-uri
#   - $FLUXNOVA_POSTGRES_DB/$FLUXNOVA_POSTGRES_USER — used by default.yml's spring.datasource (via fluxnova-up.sh)
#
# Usage (from this directory):
#   ./postgres-up.sh
#   ./postgres-down.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Prevent Git Bash/MSYS from mangling container-side paths in -v arguments.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# Shared config/data (.env, postgres, default.yml, otel-collector-config.yaml) lives
# in the parent local-dev directory — this script now sits in local-dev/services/.
LOCAL_DEV_DIR="$(cd .. && pwd)"

POD_NAME="${POSTGRES_POD_NAME:-postgres-local}"

# Load .env (KEY=VALUE lines) if present.
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi

POSTGRES_IMAGE="${POSTGRES_IMAGE:-docker.io/library/postgres:16}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
# The superuser used only for container bootstrap/init.sh — application connections use
# the mlflow/fluxnova roles that init.sh creates, not this one.
POSTGRES_SUPERUSER="${POSTGRES_SUPERUSER:-postgres}"
POSTGRES_SUPERUSER_PASSWORD="${POSTGRES_SUPERUSER_PASSWORD:-postgres}"
# Application database/role credentials — created by postgres/init.sh on first
# startup. All read from .env; never hardcoded.
MLFLOW_POSTGRES_USER="${MLFLOW_POSTGRES_USER:-mlflow}"
MLFLOW_POSTGRES_PASSWORD="${MLFLOW_POSTGRES_PASSWORD:-mlflow}"
MLFLOW_POSTGRES_DB="${MLFLOW_POSTGRES_DB:-mlflow}"
FLUXNOVA_POSTGRES_USER="${FLUXNOVA_POSTGRES_USER:-fluxnova}"
FLUXNOVA_POSTGRES_PASSWORD="${FLUXNOVA_POSTGRES_PASSWORD:-fluxnova}"
FLUXNOVA_POSTGRES_DB="${FLUXNOVA_POSTGRES_DB:-fluxnova}"
# PGDATA lives in a Podman *named volume* (not a host bind-mount) so data survives
# postgres-down.sh / pod recreation. A host bind-mount doesn't work reliably here: on
# Windows/macOS the mount is proxied through the Podman VM's 9p/virtiofs filesystem,
# which doesn't support the chown/chmod postgres's entrypoint needs to take ownership of
# PGDATA ("Operation not permitted" on initdb) — a named volume is real storage inside
# the Podman VM itself, so ownership works normally.
POSTGRES_VOLUME="${POSTGRES_VOLUME:-postgres-local-data}"
DEV_NETWORK="${DEV_NETWORK:-fluxnova-dev}"

# Same shared network as mlflow-up.sh/fluxnova-up.sh, so those pods can reach this one
# by pod name (postgres-local) — see otel-collector-config.yaml's comment on aardvark-dns
# resolving by *pod* name for sibling pods.
podman network create --ignore "$DEV_NETWORK"

# init.sh only runs against an empty PGDATA — skip re-creating the pod noisily if the
# volume already existed from a previous run. Check for existence *before* creating it.
INIT_NOTE=""
if podman volume exists "$POSTGRES_VOLUME" 2>/dev/null; then
  INIT_NOTE=" (existing volume found — postgres/init.sh will NOT re-run)"
fi
podman volume create --ignore "$POSTGRES_VOLUME"


# Idempotent: if the pod already exists (e.g. this script was run before), just make
# sure it's started rather than failing on `podman pod create`/`podman run` name clashes.
if podman pod exists "$POD_NAME"; then
  echo "Pod '$POD_NAME' already exists${INIT_NOTE} — starting it (idempotent)..."
  podman pod start "$POD_NAME" >/dev/null
else
  echo "Creating pod '$POD_NAME' (postgres:${POSTGRES_PORT}->5432)${INIT_NOTE}..."
  podman pod create --name "$POD_NAME" \
    -p "${POSTGRES_PORT}:5432" \
    --network "$DEV_NETWORK"

  echo "Starting postgres..."
  podman run -d --pod "$POD_NAME" --name postgres \
    -e POSTGRES_USER="$POSTGRES_SUPERUSER" \
    -e POSTGRES_PASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
    -e MLFLOW_POSTGRES_USER="$MLFLOW_POSTGRES_USER" \
    -e MLFLOW_POSTGRES_PASSWORD="$MLFLOW_POSTGRES_PASSWORD" \
    -e MLFLOW_POSTGRES_DB="$MLFLOW_POSTGRES_DB" \
    -e FLUXNOVA_POSTGRES_USER="$FLUXNOVA_POSTGRES_USER" \
    -e FLUXNOVA_POSTGRES_PASSWORD="$FLUXNOVA_POSTGRES_PASSWORD" \
    -e FLUXNOVA_POSTGRES_DB="$FLUXNOVA_POSTGRES_DB" \
    -v "${POSTGRES_VOLUME}:/var/lib/postgresql/data" \
    -v "${LOCAL_DEV_DIR}/postgres:/docker-entrypoint-initdb.d:ro" \
    "$POSTGRES_IMAGE"
fi

wait_for_postgres() {
  local tries="${1:-30}"
  for ((i = 0; i < tries; i++)); do
    if podman exec postgres pg_isready -U "$POSTGRES_SUPERUSER" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "Waiting for PostgreSQL to become ready..."
if ! wait_for_postgres; then
  echo "Warning: PostgreSQL doesn't seem to be responding yet. It may just need more" \
    "time — check 'podman logs -f postgres'." >&2
fi

echo
echo "Postgres:        localhost:${POSTGRES_PORT} (from sibling pods: postgres-local:5432)"
echo "MLflow database: postgresql://${MLFLOW_POSTGRES_USER}:***@postgres-local:5432/${MLFLOW_POSTGRES_DB}"
echo "Fluxnova database: postgresql://${FLUXNOVA_POSTGRES_USER}:***@postgres-local:5432/${FLUXNOVA_POSTGRES_DB} (used via JDBC)"
echo "Data volume:     ${POSTGRES_VOLUME} (podman volume inspect ${POSTGRES_VOLUME})"
echo "Logs:            podman logs -f postgres"
echo "Stop/remove:     ./postgres-down.sh"
echo
echo "Start this before mlflow-up.sh / fluxnova-up.sh, which now depend on it for their"
echo "backend store / datasource."
