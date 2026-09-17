# ui-api: FastAPI backend for the demo UI (frontend/). See ui-api/README.md.
#
# Also bundles fluxnova-mlflow-dataset, fluxnova-runner, regression/, bpmn/ and
# datasets/ so the regression.py router can shell out to `pytest regression/` (see
# ui_api/regression_runner.py) and the workflow.py router can deploy/start BPMN runs
# (see ui_api/workflow_runner.py) from inside this container.
#
# fluxnova-mlflow-dataset and fluxnova-runner are installed *editable* (`-e`, same as
# ../setup.sh does for local dev) rather than as normal packages — both
# regression/test_mlflow_regression.py and fluxnova_runner/config.py locate
# repo-relative files (fluxnova-runner/config/*.yml, datasets/, bpmn/) by walking up
# from their own `__file__`, which only lands back at a real repo root if the
# package's files stay at the path they were copied to (/app/...) instead of being
# relocated into site-packages/ by a non-editable install.
#
# Build from the repo root so all of these sibling directories are in the build
# context:
#   podman build -f ui-api/Dockerfile -t ui-api:local .
FROM python:3.11-slim

WORKDIR /app

COPY fluxnova-mlflow-dataset /app/fluxnova-mlflow-dataset
COPY fluxnova-runner /app/fluxnova-runner
COPY regression /app/regression
COPY bpmn /app/bpmn
COPY datasets /app/datasets
COPY ui-api /app/ui-api

RUN pip install --no-cache-dir \
    -e "/app/fluxnova-mlflow-dataset[dev]" \
    -e "/app/fluxnova-runner[dev]" \
    -r /app/regression/requirements.txt \
    /app/ui-api

# Bind on all interfaces inside the container — local-dev/services/frontend-up.sh and
# local-dev/compose.yaml both run this alongside frontend-local in a shared network
# namespace (the same "pod" the frontend nginx proxies /api/ into over localhost).
ENV UI_API_HOST=0.0.0.0
# regression_runner.py's/workflow_runner.py's defaults (walking up from their own
# installed location) only hold for an editable/source install — point them at the
# copies above instead.
ENV UI_API_REGRESSION_DIR=/app/regression
ENV UI_API_WORKFLOW_CONFIG=/app/fluxnova-runner/config/loan-assesment.yml

ENTRYPOINT ["ui-api"]
