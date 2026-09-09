# eval-trace-listener: standalone service that tails an MLflow experiment's trace
# store and scores newly-completed agent runs with the deterministic (trace-only)
# scorers. See eval-trace-listener/README.md.
#
# Build from the repo root so the sibling fluxnova-mlflow-dataset package (a local
# path dependency, not published to PyPI) is in the build context:
#   podman build -f eval-trace-listener/Dockerfile -t eval-trace-listener:local .
FROM python:3.11-slim

WORKDIR /app

# Install the shared trace-reading/scoring library first (own layer — changes less
# often than the listener itself) followed by the listener package.
COPY fluxnova-mlflow-dataset /app/fluxnova-mlflow-dataset
COPY eval-trace-listener /app/eval-trace-listener

RUN pip install --no-cache-dir \
    /app/fluxnova-mlflow-dataset \
    /app/eval-trace-listener

# Default to the config file baked into the image; override any individual setting
# at `podman run` time with `-e EVAL_LISTENER_<NAME>=...` env vars (see
# local-dev/services/eval-listener-up.sh for the pod-name-based URLs it needs).
ENV EVAL_LISTENER_CONFIG=/app/eval-trace-listener/config.yaml

ENTRYPOINT ["eval-trace-listener"]
