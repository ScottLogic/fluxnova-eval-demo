#!/usr/bin/env bash
# Stops and removes the mlflow-local pod created by mlflow-up.sh.
# The PostgreSQL backend store (postgres-local's "mlflow" database) is untouched — it
# lives in the separate postgres-local pod, stop that with ./postgres-down.sh if needed.
# Local artifact files (harness/.mlflow/artifacts by default) are also left in place.
set -uo pipefail

POD_NAME="${MLFLOW_POD_NAME:-mlflow-local}"

podman pod stop "$POD_NAME" 2>/dev/null || true
podman pod rm "$POD_NAME" 2>/dev/null || true

echo "Pod '$POD_NAME' stopped and removed."
