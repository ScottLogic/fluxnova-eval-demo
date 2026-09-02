#!/usr/bin/env bash
# Stops and removes the postgres-local pod created by postgres-up.sh.
# By default the named volume holding PGDATA (postgres-local-data) is not deleted, so
# MLflow/Fluxnova data survives — pass --delete-data (or set POSTGRES_DELETE_DATA=true)
# to also remove it, which forces postgres/init.sh to re-run on the next
# ./postgres-up.sh.
#
# Usage:
#   ./postgres-down.sh                # stop/remove the pod, keep the data volume
#   ./postgres-down.sh --delete-data  # stop/remove the pod AND delete the data volume
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

POD_NAME="${POSTGRES_POD_NAME:-postgres-local}"
DELETE_DATA="${POSTGRES_DELETE_DATA:-false}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) DELETE_DATA=true ;;
    -h|--help)
      echo "Usage: ./postgres-down.sh [--delete-data]"
      exit 0
      ;;
    *)
      echo "Unknown argument: '$arg' (expected --delete-data)" >&2
      exit 1
      ;;
  esac
done

# Load .env (KEY=VALUE lines) if present, for POSTGRES_VOLUME's default below.
# .env lives in the parent local-dev directory — this script sits in local-dev/services/.
if [ -f ../.env ]; then
  set -a
  source ../.env
  set +a
fi
POSTGRES_VOLUME="${POSTGRES_VOLUME:-postgres-local-data}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."

if [ "$DELETE_DATA" = "true" ]; then
  if podman volume exists "$POSTGRES_VOLUME" 2>/dev/null; then
    podman volume rm "$POSTGRES_VOLUME" >/dev/null
    echo "Data volume '$POSTGRES_VOLUME' deleted."
  else
    echo "Data volume '$POSTGRES_VOLUME' does not exist — nothing to delete."
  fi
fi
