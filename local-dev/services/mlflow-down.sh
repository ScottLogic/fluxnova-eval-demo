#!/usr/bin/env bash
# Stops and removes the mlflow-local pod created by mlflow-up.sh.
# The PostgreSQL backend store (postgres-local's "mlflow" database) is untouched — it
# lives in the separate postgres-local pod, stop that (optionally with --delete-data)
# via ./postgres-down.sh if needed.
# By default local artifact files (harness/.mlflow/artifacts by default) are left in
# place — pass --delete-data (or set MLFLOW_DELETE_DATA=true) to also remove them.
#
# Usage:
#   ./mlflow-down.sh                # stop/remove the pod, keep artifact files
#   ./mlflow-down.sh --delete-data  # stop/remove the pod AND delete artifact files
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

POD_NAME="${MLFLOW_POD_NAME:-mlflow-local}"
DELETE_DATA="${MLFLOW_DELETE_DATA:-false}"

for arg in "$@"; do
  case "$arg" in
    --delete-data) DELETE_DATA=true ;;
    -h|--help)
      echo "Usage: ./mlflow-down.sh [--delete-data]"
      exit 0
      ;;
    *)
      echo "Unknown argument: '$arg' (expected --delete-data)" >&2
      exit 1
      ;;
  esac
done

# Load .env (KEY=VALUE lines) if present, for MLFLOW_ARTIFACT_DIR's default below.
# .env / the artifact dir live in / are resolved relative to the parent local-dev
# directory — this script sits in local-dev/services/.
LOCAL_DEV_DIR="$(cd .. && pwd)"
if [ -f "$LOCAL_DEV_DIR/.env" ]; then
  set -a
  source "$LOCAL_DEV_DIR/.env"
  set +a
fi
MLFLOW_ARTIFACT_DIR="${MLFLOW_ARTIFACT_DIR:-${LOCAL_DEV_DIR}/../harness/.mlflow/artifacts}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."

if [ "$DELETE_DATA" = "true" ]; then
  if [ -d "$MLFLOW_ARTIFACT_DIR" ]; then
    rm -rf "${MLFLOW_ARTIFACT_DIR:?}"/*
    echo "Artifact files in '$MLFLOW_ARTIFACT_DIR' deleted."
  else
    echo "Artifact directory '$MLFLOW_ARTIFACT_DIR' does not exist — nothing to delete."
  fi
fi
