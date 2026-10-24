#!/bin/sh
# Shared entrypoint for Compose and pod scripts. The healthcheck gates consumers
# on both HTTP readiness and the experiment headers generated for this startup.
set -eu
rm -f /mlflow-runtime/headers.yaml
pip install --quiet psycopg2-binary
mlflow db upgrade "$MLFLOW_BACKEND_STORE_URI"
mlflow server --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
  --default-artifact-root /mlflow-artifacts \
  --host 0.0.0.0 --port 5000 --allowed-hosts '*' --cors-allowed-origins '*' &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
python /local-dev-mlflow/bootstrap.py \
  --experiment-name "$EVAL_SERVICE_EXPERIMENT_NAME" \
  --output /mlflow-runtime/headers.yaml
wait "$server_pid"
