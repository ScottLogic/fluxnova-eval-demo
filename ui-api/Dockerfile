# ui-api: FastAPI backend for the demo UI (frontend/). See ui-api/README.md.
#
# Also bundles fluxnova-mlflow-dataset, fluxnova-runner, eval-trace-listener,
# eval-service-worker, regression/, bpmn/ and datasets/ so the regression.py router
# can shell out to `pytest regression/` (see ui_api/regression_runner.py), the
# workflow.py router can deploy/start BPMN runs (see ui_api/workflow_runner.py), and
# the evals.py router can read the listener's/worker's real scorer definitions (see
# ui_api/eval_definitions.py) from inside this container.
#
# fluxnova-mlflow-dataset and fluxnova-runner are installed *editable* (`-e`, same as
# ../setup.sh does for local dev) rather than as normal packages — both
# regression/test_mlflow_regression.py and fluxnova_runner/config.py locate
# repo-relative files (fluxnova-runner/config/*.yml, datasets/, bpmn/) by walking up
# from their own `__file__`, which only lands back at a real repo root if the
# package's files stay at the path they were copied to (/app/...) instead of being
# relocated into site-packages/ by a non-editable install. eval-trace-listener and
# eval-service-worker have no such repo-relative assumptions, so a normal install is
# fine for those two.
#
# Build from the repo root so all of these sibling directories are in the build
# context:
#   podman build -f ui-api/Dockerfile -t ui-api:local .
FROM python:3.11-slim

WORKDIR /app

COPY fluxnova-mlflow-dataset /app/fluxnova-mlflow-dataset
COPY fluxnova-runner /app/fluxnova-runner
COPY eval-trace-listener /app/eval-trace-listener
COPY eval-service-worker /app/eval-service-worker
COPY regression /app/regression
COPY bpmn /app/bpmn
COPY datasets /app/datasets
COPY ui-api /app/ui-api

RUN pip install --no-cache-dir \
    -e "/app/fluxnova-mlflow-dataset[dev]" \
    -e "/app/fluxnova-runner[dev]" \
    /app/eval-trace-listener \
    /app/eval-service-worker \
    -r /app/regression/requirements.txt \
    /app/ui-api

# Bind on all interfaces inside the container — local-dev/services/frontend-up.sh and
# local-dev/compose.yaml both run this alongside frontend-local in a shared network
# namespace (the same "pod" the frontend nginx proxies /api/ into over localhost).
ENV UI_API_HOST=0.0.0.0
# regression_runner.py's/workflow_runner.py's defaults (walking up from their own
# installed location) only hold for an editable/source install — point them at the
# copies above instead. loan_approval_process_ai.yml/LoanApprovalProcess_AI.bpmn is
# the current workflow — the older loan-assesment(-eval).yml/.bpmn files are
# deprecated (see workflow_runner.py's _default_config_path).
ENV UI_API_REGRESSION_DIR=/app/regression
ENV UI_API_WORKFLOW_CONFIG=/app/fluxnova-runner/config/loan_approval_process_ai.yml

ENTRYPOINT ["ui-api"]
