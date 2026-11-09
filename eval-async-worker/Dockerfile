# eval-async-worker: external-task worker for the non-blocking Eval service task
# (topic agent-output-eval-async). See eval-async-worker/README.md.
#
# Build from the repo root so the sibling fluxnova-mlflow-dataset package (a local
# path dependency, not published to PyPI) is in the build context:
#   podman build -f eval-async-worker/Dockerfile -t eval-async-worker:local .
FROM python:3.11-slim

WORKDIR /app

# Install the shared trace-reading/scoring library first (own layer — changes less
# often than the worker itself) followed by the eval-async-worker package.
COPY fluxnova-mlflow-dataset /app/fluxnova-mlflow-dataset
COPY eval-async-worker /app/eval-async-worker

RUN pip install --no-cache-dir \
    /app/fluxnova-mlflow-dataset \
    /app/eval-async-worker

# Default to the config file baked into the image; override any individual setting
# at `podman run` time with `-e EVAL_ASYNC_<NAME>=...` env vars (see
# local-dev/services/eval-async-up.sh for the pod-name-based URLs it needs).
ENV EVAL_ASYNC_CONFIG=/app/eval-async-worker/config.yaml

ENTRYPOINT ["eval-async-worker"]
