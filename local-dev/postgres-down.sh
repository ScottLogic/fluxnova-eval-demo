#!/usr/bin/env bash
# Stops and removes the postgres-local pod created by postgres-up.sh.
# The named volume holding PGDATA (postgres-local-data by default) is not deleted, so
# MLflow/Fluxnova data survives — run `podman volume rm postgres-local-data` manually to
# force postgres-init/init.sh to re-run on the next ./postgres-up.sh.
set -uo pipefail

POD_NAME="${POSTGRES_POD_NAME:-postgres-local}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
