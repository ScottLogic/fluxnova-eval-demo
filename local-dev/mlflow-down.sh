#!/usr/bin/env bash
# Stops and removes the mlflow-local pod created by mlflow-up.sh.
# The SQLite backend store (harness/.mlflow/mlflow.db by default) is not deleted.
set -uo pipefail

POD_NAME="${MLFLOW_POD_NAME:-mlflow-local}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
