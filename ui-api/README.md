# ui-api

FastAPI backend for the demo UI (`frontend/`). There's no HTTP API for regression, the BPMN runner, or the eval
services elsewhere in this repo — to keep those core folders (`regression/`, `fluxnova-runner/`,
`eval-async-worker/`, `eval-service-worker/`) purely about *how you'd build this for real* rather than cluttered
with UI-only plumbing, this API lives on its own and wraps them as a library/CLI instead of embedding API code inside
them. See the [local UI walkthrough](../local-dev/README.md#frontend-and-ui-api).

One router per concern: `regression.py`, `workflow.py`, `evals.py` (all under `src/ui_api/routers/`).
`evals.py` exposes scorer definitions. ui-api imports `eval-async-worker` and `eval-service-worker` as dependencies
to read their scorer lists. It no longer talks to eval-async-worker at runtime (no auto-eval endpoints, no
`UI_API_EVAL_ASYNC_URL`); its sample rate is controlled only on its own `:8092` endpoint.

## Regression endpoints

`regression.py` drives `regression/test_mlflow_regression.py` as a background subprocess (see
`src/ui_api/regression_runner.py` for why it shells out rather than importing the suite) —
requires `pytest-json-report` (`regression/requirements.txt`) for structured per-test results.

```
GET  /api/regression/tests           -> {"tests": [{"name": "test_mlflow_regression.py::test_...", "description": "..."}, ...]}
GET  /api/regression/goldens         -> {"goldens": [...]}
POST /api/regression/runs            -> {"runId": "<uuid>"}                      (202, starts in the background)
GET  /api/regression/runs/{run_id}   -> {"runId": ..., "status": "running"}
                                      -> {"runId": ..., "status": "passed" | "failed", "exitCode": ..., "summary": {...}, "tests": [...]}
                                      -> {"runId": ..., "status": "error", "exitCode": ..., "output": "..."}  (crashed before writing a report)
```

The suite needs `fluxnova-runner`/`fluxnova-mlflow-dataset` installed (see `../setup.sh`'s shared `.venv`) — if
ui-api itself isn't running from that same environment, point it at the right interpreter with
`UI_API_REGRESSION_PYTHON=/path/to/.venv/bin/python`. `UI_API_REGRESSION_DIR` and `UI_API_GOLDENS_PATH` override the
suite directory and goldens file.

## Workflow endpoints

`workflow.py` calls `fluxnova_runner.client.Client`/`RunnerConfig` directly (see `src/ui_api/workflow_runner.py`) —
no subprocess needed here, unlike regression, since deploying a BPMN and starting a process instance are just a
couple of fast HTTP calls to Fluxnova rather than a slow live-agent test suite.

```
GET  /api/workflow/config  -> {"processKey": "...", "variables": {...},
                               "agentConfig": {"provider","model","systemPrompt"} | null,
                               "guardrail": {"taskId","taskName","minScore","requiredScorers","sampleRate",
                                             "forceReviewEveryN","configuredInBpmn","overridable"} | null}
POST /api/workflow/runs             body: {"requestedAmount": 60000, ...}   -> {"instanceId": "<id>"}   (202)
                                     (body keys override the config file's default `variables` — omit to use
                                      the defaults from fluxnova-runner/config/loan_approval_process_ai.yml)
GET  /api/workflow/runs/{instance_id} -> {"instanceId": ..., "status": "active", "variables": {...}, "stages": [...]}
                                       -> {"instanceId": ..., "status": "completed" | "terminated" | "error",
                                           "state": "COMPLETED", "variables": {...}, "stages": [...]}
```

`guardrail` is read from the `agent-output-eval` service task's input parameters in `bpmn_path` only. `stages`
nests Call Activity children.

Each `POST` deploys the configured BPMN using duplicate filtering (reusing unchanged
resources or creating a new version), preserving earlier instances, history and human tasks (unlike `fluxnova-run`,
which cascade-deletes earlier deployments), and
starts the config's mock external-task workers once per ui-api process (they run forever, answering whichever
matching task shows up — no need to restart them per run). Which workflow config file is used is controlled by
`UI_API_WORKFLOW_CONFIG` (defaults to `fluxnova-runner/config/loan_approval_process_ai.yml`, resolved relative to the repo
root for a source/editable install — the ui-api Docker image sets this explicitly instead).

## Run locally

`./setup.sh` installs UI API into the shared environment. Container startup passes
internal Fluxnova/MLflow URLs, experiment names and judge-provider settings
explicitly; see [networking/configuration](../local-dev/README.md#frontend-and-ui-api).
Per-test regression results include `scorers` with name/status/value/rationale; their
replayable gate reports are retained in MLflow under `regression/<scenario>/`.

`GET /api/evals/definitions` lists the shared scorer objects: each has `name`, `description`, `deterministic`,
`usedInAutoEval` (eval-async-worker), `usedInEvalServiceWorker` and `usedInRegression`.

```bash
cd ui-api
pip install -e ".[dev]"
ui-api                    # serves on http://127.0.0.1:8090
UI_API_PORT=8091 ui-api   # override host/port via UI_API_HOST / UI_API_PORT env vars, or --host/--port flags
```

CORS is open to the Vite dev server's origin (`http://localhost:5173`, see `frontend/vite.config.ts`) by default —
override with a comma-separated `UI_API_CORS_ORIGINS`.

```bash
curl http://127.0.0.1:8090/health   # {"status": "ok"}
```

## Tests

```bash
pytest
```
