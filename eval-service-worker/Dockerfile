# eval-service-worker: BPMN external-task worker that scores a just-completed
# agentic subprocess run using MLflow's decision_quality judge (trace data only).
#
# Build from the repo root so the sibling fluxnova-mlflow-dataset package (a local
# path dependency, not published to PyPI) is in the build context:
#   podman build -f eval-service-worker/Dockerfile -t eval-service-worker:local .
FROM python:3.11-slim

WORKDIR /app

# Install the shared trace-reading/scoring library first (own layer — changes less
# often than the worker itself) followed by the worker package.
COPY fluxnova-mlflow-dataset /app/fluxnova-mlflow-dataset
COPY eval-service-worker /app/eval-service-worker

RUN pip install --no-cache-dir \
    /app/fluxnova-mlflow-dataset \
    /app/eval-service-worker

# All settings have hardcoded defaults (see src/eval_service_worker/config.py) —
# override any of them at `podman run` time with `-e EVAL_SERVICE_<NAME>=...` env
# vars or by appending CLI flags after the image name. See local-dev/eval-service-up.sh
# for the env vars this container actually needs (pod-name-based URLs).
ENTRYPOINT ["eval-service-worker"]
