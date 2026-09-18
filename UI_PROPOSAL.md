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
10. **Eval config UI** — add controls in the Workflow run tab to toggle "auto-eval (listener)" and "eval service
    worker" independently for the next run; wired into the workflow-run request from step 8/9.
11. **Trace listener live sampling** — add a `sample_rate` setting (0.0–1.0, i.e. "score none" / "1 in 10" /
    "score every trace") to `eval-trace-listener`'s `ListenerConfig`, plus a small always-on control surface in
    that same process (e.g. a minimal HTTP endpoint, `GET`/`PUT` the current rate) so the rate can be changed
    while the listener is already running — no restart needed. Each poll cycle reads the current rate and
    probabilistically skips scoring newly-completed traces accordingly (`0.0` = skip all, `1.0` = score every
    one it finds).
12. **Wire the auto-eval toggle to real sampling** — supersedes step 10's "just a UI-visible flag" behaviour
    for this toggle specifically: `ui-api`'s `evals.py` gets an endpoint that forwards to the trace listener's
    new control surface from step 11, and the Workflow tab's "Auto-eval (listener)" toggle calls it whenever
    flipped — off sets the sample rate to `0.0` ("none"), on sets it to `1.0` ("100%"). The "eval service
    worker" toggle is unaffected — it stays a per-run `skipEvalServiceWorker` process variable (steps 9/10).
13. **Eval definitions API** — endpoint(s) exposing which evals are configured to run for the listener
    (`eval-trace-listener/config.yaml`) and for the service worker (its config source).
14. **Eval definitions UI** — display the listener evals and service worker evals in the Evals tab from
    step 13.
15. **Metrics/tracing view** — read-only panel in a new Telemetry tab showing metrics and traces Fluxnova
    exports, plus link-outs to Grafana and the MLflow dashboard.
16. **Restore external links** — port over the `FinosProjectsPanel.tsx` equivalent (a static link list to
    AIGF, CCC, CALM, Fluxnova) from the steel thread demo into a relevant tab. The interactive
    `CalmArchitectureVisualizer.tsx` (a React Flow graph, needing a new `@xyflow/react` dependency and a
    `*.calm.json` describing this repo's own architecture, which doesn't exist yet) is deliberately **out of
    scope for now** — a plain link-out to the CALM Hub is enough here; porting the full visualizer is
    future work if wanted later.
17. **Polish pass** — loading/error states, responsive layout check, README for `frontend/` + `ui-api/`
    covering how to run the UI and API layer together.

Follow-ups:
Home page:
- Should have a contents with a breif description of each tab
- Projects list should be on the right unless screen width does not allow.

Loan Assesment
- Integrate the Finos AI Govenanvce and open catalog link from steel thread using the useCase.ts file

Regression tests:
- Should have each deterministic test as its own line item rather than all as one
- I want a nicer view of this. It should show what is happening when I run the tests rather than wait for them to complete.
- I also want to display the description of the test along with the name, result ect in a nice way rather than as a tooltip

Workflow run:
- Should include the 
- Should show a link out to the fluxnova monitoring UI
- Would be nice to see the bpmn progress (same view as monitor in Fluxnova) if possible (how much effort?)
- I need more information. Before a run I want to see details of model, provider, prompt etc
- During the run I want to see what stage things are at using the history api from Fluxnova

Evals
- I want this to be a complete list of scorers. It should give a description of what scoreres are and then for each show
- the name, description, if it is used in auto eval, if used in eval service task, if used in regression testing
- Deterministic / non deterministic scorers should be colour coded to distinguish

Architecture
- I want the nodes to be redesigned to match the layout I have in the Fluxnova EDD.png diagram. Fluxnova should be larger to highlight it
- I want nodes to be clickable with a description showing when I click. This should be possible using Toolbar and custom nodes https://reactflow.dev/examples/nodes/node-toolbar
- 