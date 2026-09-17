# UI PROPOSAL PLAN

I want to implement a UI which I can use for the demo using
the [steel thread demo](C:\dev\ai-steel-thread-demo\frontend) as a basis.
The UI should look much the same as the steel thread demo overall but with a cleaner implantation following best
practice for frontend / react development.

The UI should have the following pages / tabs

- Regression tests - I want to view what regression tests are available / trigger a run and see results
- Workflow run - I want to be able to trigger a run of the bpmn (very similar to what is already there) - using random input I can alter if requried.

Evals - I want to be able to toggle auto-eval and eval service worker on and off independantly for each run.
I want to see what evals are run for both auto-eval (listener) and service worker
I want to see what metrics and tracing fluxnova exports.
I want to keep existing links/functionality with other FINOS services such as CALM and CCC etc

## Implementation plan

Stack: React + Vite + TypeScript, mirroring `ai-steel-thread-demo/frontend`. New frontend lives in a
top-level `frontend/` folder.

There's currently no HTTP API for regression, the bpmn runner, or the eval services. To keep the demo's
core folders (`regression/`, `fluxnova-runner/`, `eval-trace-listener/`, `eval-service-worker/`) purely
about *how you'd build this for real* — not cluttered with UI-only plumbing — the new API lives in its
own top-level `ui-api/` FastAPI app, one router per concern (`regression.py`, `workflow.py`, `evals.py`).
Each router imports/subprocesses the existing packages as a library/CLI rather than embedding API code
inside them, so removing `ui-api/` later would leave the core demo untouched.

**Regression trigger mechanics** (answering "how does the API trigger the tests?"): the API runs pytest
out-of-process, e.g. `pytest regression/test_mlflow_regression.py -v --json-report --json-report-file=<tmp>`,
using the `pytest-json-report` plugin (new dependency, added to `regression/pyproject.toml`/requirements)
to get structured pass/fail/timing per test. The list of available tests comes from
`pytest --collect-only -q` against the same file. The API starts the subprocess in the background, returns
a run id immediately, and the UI polls a status endpoint until the json report file appears (mirrors how
`test_mlflow_regression.py` itself can take a long time per golden).

Each step below is a single commit, small enough to review on its own, and leaves the app in a working state.

1. **Scaffold frontend** — `npm create vite@latest frontend -- --template react-ts`, copy over base
   config/lint/prettier setup from the steel thread demo, add root layout with tab navigation
   (Regression / Workflow / Evals) and empty placeholder pages. No backend calls yet.
2. **Deploy the frontend via podman/compose** — add a multi-stage `frontend/Dockerfile` (node build stage,
   then serve the static `dist/` with nginx, mirroring the `eval-service-worker`/`eval-trace-listener`
   Dockerfiles' pattern of building from source) and a `frontend-local` service in
   `local-dev/compose.yaml`, so the UI starts the same way as every other service
   (`podman compose up -d` / `podman compose --profile eval up -d`). No profile gating needed since the
   frontend has no eval-only dependencies, but it depends on `fluxnova-local` the same way
   `eval-service-worker-local` does (`host.containers.internal`, since `fluxnova-local` runs on
   `network_mode: host`). Nginx proxies `/api` to `fluxnova-local`/`ui-api` so the container works
   standalone, matching the Vite dev server's `/api` proxy in step 1.
3. **Port shared visual shell** — port over `App.css`/`index.css` styling and any generic layout/badge
   components from the steel thread demo needed for a consistent look (e.g. header, nav, status badges).
4. **Scaffold `ui-api`** — new FastAPI app skeleton (`ui-api/pyproject.toml`, `main.py`, empty routers),
   CORS configured for the Vite dev server, a `/health` endpoint. No real logic yet.
5. **Regression API** — `regression.py` router: list available tests (`pytest --collect-only`), trigger a
   run in the background (`pytest ... --json-report`), and a status/result endpoint the UI polls, per the
   mechanics above.
6. **Regression tab UI** — page listing available tests, a "run" button, a results view (pass/fail,
   timing) polling the API from step 5, and a link out to the MLflow dashboard for the regression
   experiment.
7. **Workflow run API** — add a `workflow.py` router to trigger a bpmn run with a given input payload and
   fetch run status, reusing the existing `fluxnova-runner` client/config used by the steel thread demo.
8. **Workflow run tab UI** — port/rebuild the run trigger form from the steel thread demo
   (`LoanApprovalForm.tsx` equivalent), allow editing the random input, show run/status log
   (`ProcessStatusLog.tsx` equivalent) using the API from step 7.
9. **Eval toggle API** — `evals.py` router with an endpoint to set a process variable default for new
   workflow runs (e.g. `skip_eval_service_worker`) so the eval-service-worker step in the BPMN can be
   bypassed per run; the trace listener stays always-on, so its "toggle" just flips a UI-visible flag the
   workflow-run request includes. Update the bpmn(s) so the eval-service-worker task is gated on that
   process variable.
10. **Eval config UI** — add controls in the Evals tab to toggle "auto-eval (listener)" and "eval service
    worker" independently for the next run; wired into the workflow-run request from step 8/9.
11. **Eval definitions API** — endpoint(s) exposing which evals are configured to run for the listener
    (`eval-trace-listener/config.yaml`) and for the service worker (its config source).
12. **Eval definitions UI** — display the listener evals and service worker evals in the Evals tab from
    step 11.
13. **Metrics/tracing view** — read-only panel in the Evals tab showing metrics and traces Fluxnova
    exports, plus link-outs to Grafana and the MLflow dashboard.
14. **Restore external links** — port over the existing links/panels to other FINOS services (CALM, CCC)
    from the steel thread demo (`CalmArchitectureVisualizer.tsx`, `FinosProjectsPanel.tsx` equivalents)
    into the relevant tabs.
15. **Polish pass** — loading/error states, responsive layout check, README for `frontend/` + `ui-api/`
    covering how to run the UI and API layer together.

Follow-ups:
Regression tests:
- Should have a description of what the regressions tests are for and why they are useful
- Should have the golden use cases alongside the tests in a separate component. I want to be able to click through each golden and view it in the UI.
- Should give a description of each test returned from the api. This should be pulled from the tests own docstring if possible 
- Should have each deterministic test as its own line item rather than all as one
- Nice to have - Give better view of the tests running - can we stream what is happening in any way easily? Propose a solution first.

