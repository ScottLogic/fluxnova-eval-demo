# regression

The end-to-end **MLflow agent regression suite** for the Fluxnova loan-assessment agent — the project's gating check
against behavioural regressions. It lives at the repo root (rather than inside any one package) because it drives the
whole stack: it depends on `fluxnova-runner` (to run the live agent) and `fluxnova-mlflow-dataset` (for the shared
judges/scorers).

## What it does

`test_agent_passes_golden[<scenario>]` is parametrized once for each of the six
goldens in [`datasets/loan-assessment/goldens.json`](../datasets/loan-assessment/goldens.json).
Each test drives the live agent once via `fluxnova-runner`, then scores that actual
output with every scorer in one `mlflow.genai.evaluate()` call. Four gate groups:

- `decision_quality`: an unambiguous evidence-backed APPROVE/REJECT, judged semantically.
- `matches_golden`: agreement with the golden decision/evidence, thresholded at `GOLDEN_MATCH_THRESHOLD`.
- `ALL_DETERMINISTIC_SCORERS` (15): tool selection, errors, duplicates, risk/income ordering,
  inference budget, evidence keywords, plain final recommendation line and captured arguments.
- `evidence_citation`: grounded evidence, thresholded at `REGRESSION_EVIDENCE_CITATION_THRESHOLD`.

All groups must pass. `@mlflow.test` records one outcome per scenario. The
`pytest-json-report` plugin exposes every scorer's name/status/value/rationale in
`metadata.scorers` for the UI API; replayable reports preserve the process ID and
captured output/tool data as well. `./setup.sh` installs the plugin.

### One real run per golden, one evaluation of that frozen result

The combined suite follows upstream's per-scenario execution model: it captures
one actual output and scores all gates together, replacing the older cached
`predict_fn`/four-test layout. No gate reruns the live agent. Use `pytest -k
<scenario>` to run one golden; the UI API lists the same six parametrized tests.

### Scorers and how the data is retrieved

Only regression runs `matches_golden`, which needs a reference answer from the
golden dataset. The other judges are also used by the trace-based evaluation services.

**How scorer inputs are sourced.** Every scorer value comes directly from
Fluxnova REST history/process variables, independently of trace export:

- `outputs` — the agent's *actual* final answer, read from the run's `_agentConversationHistory` process variable
  (`fluxnova_runner.agent_output`).
- `inputs.input_variables` — the applicant-facing variables the golden started the BPMN with.
- `inputs.tool_calls` / `inputs.iterations` — the agent's tool-call history (name, status, arguments) and loop
  iteration count, parsed from the same `_agentConversationHistory` (now enriched with `toolCalls`/`toolResult` per
  turn) plus the `_agentLoopIndex` process variable (`fluxnova_runner.agent_tool_calls`) — the process-variable
  equivalent of what `eval-service-worker`/`eval-trace-listener` read off the OTel trace's `execute_tool` spans.
- `expectations.expected_output` — the golden's reference answer (consumed by `matches_golden`).

The suite also best-effort tags each raw trace `source=regression` so the listener
can skip it. Raw traces follow `EVAL_SERVICE_EXPERIMENT_NAME`. Evaluation runs share
that experiment by default; `MLFLOW_EXPERIMENT_NAME` can select a separate regression
experiment (including a fresh `-v2` name when preserving legacy artifact locations).

## Running

From the repo root, with the shared `.venv` active (see the root [README](../README.md#first-time-setup)):

```bash
python -m pytest regression -v -rs
# or a single test:
python -m pytest regression/test_mlflow_regression.py -v -rs
```

**Prerequisites:** the full live stack must be up (Fluxnova engine, Postgres, OTel Collector, MLflow — see
[`local-dev/README.md`](../local-dev/README.md)). The suite **skips cleanly** if the engine or tracking store isn't
reachable rather than failing. The LLM-as-judge scorers (`decision_quality`, `matches_golden`, `evidence_citation`)
default to OpenAI, so `OPENAI_API_KEY` must be set in the shell running pytest; set `LLM_JUDGE_PROVIDER=ollama`
instead to judge fully locally (Ollama must then be running with `gemma4:e2b` pulled).

## Validation sequence

Use the shared `.venv` from the repository root. Stop any separately running demo
mock-worker terminal before the live regression; the suite starts its own pool.

1. **Prepare the stack.** Follow [local setup](../local-dev/README.md#quick-start-pods).
   If upgrading an old store, follow the [artifact-experiment upgrade](../local-dev/README.md#upgrade-experiments-created-with-container-local-artifact-paths)
   and use fresh experiment names while preserving historical results. Recreate
   affected pods and rebuild evaluation images after source changes. Restarting
   the VM alone does not update container environments.
2. **Check artifact transport before model calls:**
   ```bash
   python local-dev/mlflow/check_artifacts.py
   ```
   Expected: upload/download succeeds with a `mlflow-artifacts:/...` URI. A host
   client must not attempt to write directly to `/mlflow-artifacts`.
3. **Run offline checks** using the [separate package suites](../local-dev/README.md#port-overrides-and-checks).
   For real HTTP artifact/report transport against a temporary isolated server:
   ```bash
   RUN_MLFLOW_PROXY_TEST=1 python -m pytest local-dev/tests/test_artifact_proxy.py -q
   ```
   This makes no model calls. The normal local-dev suite intentionally skips this
   opt-in test.
4. **Check the judge independently of the agent:**
   ```bash
   python -m regression.calibrate
   ```
   Expected: eight frozen examples, zero mismatches: four valid responses receive
   `yes` and four deliberately invalid responses receive `no`. Inspect rationales
   and retain reports when assessing repeatability. An all-yes judge, missing
   verdicts or provider failures are not calibration success.
5. **Run all four live gates:**
   ```bash
   python -m pytest regression -v -rs
   ```
    Expected: six parametrized scenarios with four passing gate groups, no artifact-path
   warnings and no skips. Inspect the experiment named by `MLFLOW_EXPERIMENT_NAME`
    (the default name or your `-v2` override), its `regression/<scenario>/*.json` artifacts and
   local report copies. Scored model-quality failures differ from infrastructure
   errors; use the scenario, process ID and rationale before changing a threshold.
6. **Replay captured results**, substituting the run ID printed by the suite:
   ```bash
    python -m regression.calibrate --mode deterministic --report local-dev/.mlflow/reports/<run-id>/<scenario>/deterministic.json
    python -m regression.calibrate --report local-dev/.mlflow/reports/<run-id>/<scenario>/decision_quality.json
   ```
   The first is offline; the second makes judge calls on the frozen outputs.
   Neither executes the agent. Old inefficient outputs should still fail current
   budgets; replay does not rewrite history or alter the original results.
7. **Check online scoring and persistence** with the [demo walkthrough](../local-dev/README.md#demo-walkthrough):
   inspect trace payloads, assessments, `evalPassed`/`evalRationale`, dashboards,
   and retained results after normal teardown/recreation.

When reporting results, include platform/Podman versions, model and rubric versions,
calibration report paths, regression run ID, inference counts, artifact smoke result
and online workflow outcome. All four live regression gates have passed local
Apple Silicon validation; repeat these checks after workflow, scorer or model changes.

### Combined upstream-tree validation — 2026-10-25

Upstream `main` at `771e8c8` was merged in `805113e`, reconciling its UI API,
listener sampling and per-golden regression refactors with the portability and
evaluation changes. The environment/models are the same as the earlier matrix
below; rebuilt ARM64 Python containers used Python 3.11.17 (host: 3.11.13).

| Check | Integrated-tree result |
| --- | --- |
| Separate Python suites | Shared dataset **131**, runner **50**, worker **23**, listener **38**, UI API **24** passed; local-dev **73 passed, 1 expected opt-in skip**. |
| Isolated HTTP integration | `RUN_MLFLOW_PROXY_TEST=1 python -m pytest local-dev/tests/test_artifact_proxy.py -q`: **1 passed**, including real evaluation schema/report upload/download. |
| Frontend | `npm ci`, `npm run build` and `npm run lint` completed; lint reported three upstream warnings and the build reported a large-chunk warning. |
| Frozen calibration | Eight labels, zero mismatches; run `40598fb63c6b4163af63e915cdbccf0c`. |
| Pods, through nginx/UI API | UI run `063dfed1f08947b3b0eb3e3bcf1a58e7`; MLflow run `6df4f167b74d492d9f9bf571fa218317`: **6 passed**, all **18 scorers** (15 deterministic + 3 judges), four gate groups. Every scenario used four inferences. |
| Compose, through nginx/UI API | UI run `73408eb05aa846b08b82878633d938fd`; MLflow run `bafdee4e184d4a31a00648ef83691738`: **6 passed**, same scorer/gate groups. Self-employed approval used three inferences; all others used four. |
| Frozen replay | All six outputs passed deterministic and semantic replay for each orchestration; replay runs `c17963d64b7b42af8a968b608d164d68` and `f8d3faab160046ffb38c9bb1d2550992`. Each source run retained **24** per-scenario gate reports. |
| UI integration | Six test descriptions, progress polling, scorer statuses/rationales, 18 scorer definitions, nested workflow stages, and listener off/on sampling control verified through HTTP APIs behind nginx under both orchestrations. |
| Online routing | Both pod and Compose controlled-eval workflows reached approval on a genuine scoring pass and failed-evaluation review on a deliberately injected false result; worker restored afterward. |
| Artifacts/readiness/observability | Artifact round-trips passed on both orchestrations. Recreated Compose engine and UI API reported healthy; collector scrape target UP, Grafana healthy, dashboard provisioned. |
| Persistence | Old failed/successful runs, trace payload/assessments, eight old/new approval/review tasks and all 48 integrated gate reports re-read after recreation/restart; three UI histories re-read after the preservation fix and return to pods. |

UI API persistence validation exposed upstream's cascading deployment deletion on
each workflow start ([#32](https://github.com/ScottLogic/fluxnova-eval-demo/issues/32)).
The first pod UI instance was deleted by the next launch before the fix. Commit
`37ad0f7` removes that implicit deletion; a new unit check plus consecutive live
launches and a Compose-to-pods switch verified that the prior and new histories
remain available. This targeted follow-up did not change regression scoring.

The VM shutdown recurred even after an independent Terminal start. After another
user restart, final persistence/readiness checks passed and a fresh pod UI workflow
`31aa9a0b-d024-11f1-ae8f-1efa7cc6c1d1` received `evalPassed=true`. The shutdown
cause remains unconfirmed. UI behavior was checked programmatically, not through
a browser/visual acceptance test. Windows/WSL, Intel macOS, native Linux, other VM
providers, native ARM64 Fluxnova, Ollama, AI Gateway sampling, IDE breakpoints,
fresh-machine/destructive-reset and load/soak testing remain unvalidated.

### Recorded Apple Silicon validation — 2026-10-25 (before upstream integration)

Environment: macOS ARM64, Python 3.11.13, Podman 5.8.1 with an existing
`libkrun` VM (8 CPUs, approximately 30 GiB RAM), MLflow 3.16.0. Fluxnova runs
as AMD64; the agent is `gpt-4o`, the decision judge `gpt-4.1-mini` (rubric 2),
and the auxiliary judges `gpt-4o-mini`.

| Check | Recorded result |
| --- | --- |
| Package unit suites | Shared dataset 120, runner 49, worker 23 and listener 29 passed in separate suites. |
| Local startup/integration checks | 69 passed, one expected opt-in skip; the real HTTP artifact-proxy test also passed separately. |
| Frozen calibration | All eight labels matched repeatedly; default-model confirmation run `d7102aab47e54f05a0db4d72550d61e0`. |
| Pod live regression | All four gates passed, run `6f033e5d76004b29aff879a389b0bf12`; deterministic and six-output judge replay passed. |
| Compose live regression | All four gates passed, run `87cb04a4771d4b4581f100e73e16daeb`; deterministic and six-output judge replay passed. |
| Online evaluation routing | Approval and controlled failed-evaluation review routes verified with both pod and Compose orchestration. |
| Artifact transport and persistence | HTTP upload/download passed; historical failed/successful runs, trace payloads/assessments, four regression reports and four approval/review tasks survived orchestration recreation and a VM restart. |
| Fresh workflow after restart | Process `f9737fdd-d016-11f1-a555-0aa8c5b19949` completed in four inferences; trace `tr-f62e531178d8d10bb18e8481bef2c289` has nine spans, decision-quality `yes`, evidence score `1.0` and passing applicable deterministic assessments. |
| Observability after restart | Collector scrape target UP; Grafana database healthy and the provisioned GenAI dashboard available. |

Earlier automated validation sessions experienced unexpected orderly VM shutdowns.
The final post-restart checks above passed after starting the VM from an independent
user Terminal; this does not establish the cause of those earlier shutdowns.
Windows, Intel macOS, native Linux and the optional Ollama path remain unvalidated.
Run IDs refer to the retained local development store; reproduce results with the
sequence above when using a different store or changing the workflow/scorers/models.

## Configuration

Every gate group writes `regression/<scenario>/<gate>.json` to its MLflow run and a local copy
under `local-dev/.mlflow/reports/<run-id>/<scenario>/` (`REGRESSION_REPORT_DIR` overrides the
root). Reports contain scenario labels, engine process instance IDs, captured actual
outputs, expectations, tool calls, total inference counts and scorer verdicts/errors/
rationales. Failures list every affected scenario/scorer, rather than stopping at
the first deterministic scorer. Profile-driven not-applicable checks remain skips;
missing applicable verdicts, missing rows and scorer errors fail the gate.

The four groups use one live agent result per golden. Saved reports can be
used for judge calibration/replay without another agent execution.

### Judge calibration and frozen replay

The decision-quality rubric is versioned (`2`) and accepts concrete evidence
anywhere in the response, including bullets before a final recommendation. It
still rejects absent evidence, invented/contradictory facts and deferred or
contradictory decisions. Semantic judging does not impose an output layout.
The separate deterministic `final_recommendation_format` check enforces the new
agent contract: evidence and justification first, then a plain final line exactly
`APPROVE` or `REJECT`. The updated BPMN requests that format explicitly.

```bash
python -m regression.calibrate                         # 8 frozen positive/negative judge cases
python -m regression.calibrate --report local-dev/.mlflow/reports/<run-id>/<scenario>/decision_quality.json
python -m regression.calibrate --mode deterministic --report local-dev/.mlflow/reports/<run-id>/<scenario>/deterministic.json
```

Judge mode uses model calls, but never starts/deploys a workflow. The built-in suite
has four expected `yes` and four deliberately invalid expected `no` responses; an
all-yes judge fails calibration. Report replay expects `yes` for each recorded
workflow output. `--model` selects an explicit candidate without changing the agent.
The expected raw verdict mean for this balanced calibration set is `0.5`; success
is **zero expectation mismatches**, not an all-positive verdict mean. The default
semantic judge is `gpt-4.1-mini`, selected after `gpt-4o-mini` repeated a false-negative
on the valid rejection example; golden matching/evidence citation remain separate.
Auxiliary judges request structured JSON on OpenAI (native JSON mode on Ollama).
A whole-response JSON code fence is accepted, but malformed payloads, non-finite/
out-of-range scores and missing rationales still fail; thresholds are unchanged.
Judge results/rationales, actual model and rubric version are saved in MLflow's
separate `fluxnova-decision-quality-calibration-v2` experiment and locally under
`local-dev/.mlflow/calibration/`; `--output` selects a local filename. Missing/error
verdicts and expectation mismatches exit non-zero. Deterministic mode needs neither
a model nor a tracking server and re-evaluates captured inputs with current scorers.

Offline tests check wiring, reporting, negative-case handling and output format;
they do not establish judge quality. Run the frozen suite against the configured
model before claiming calibration passes. Follow the [validation sequence](#validation-sequence)
for the ordered upgrade and end-to-end checks.

To reproduce live calibration against an isolated temporary MLflow store, use
`RUN_MLFLOW_PROXY_TEST=1 RUN_LLM_CALIBRATION_TEST=1 python -m pytest local-dev/tests/test_artifact_proxy.py -q`.
This explicit opt-in makes eight judge calls with the configured credentials and
keeps the demo store unchanged. Standard unit tests and proxy-only checks make no model calls.

### Efficiency contract

`iterations` means total LLM inference calls **including the final response** in
both engine-variable and trace consumers. The normal budget is four calls:
fraud+credit together, income verification, affordability after income, final answer.
Collateral should be batched with income where possible; a separate collateral
round permits a fifth call. Five calls without collateral, or six with collateral,
still fail. The BPMN prompt explicitly requests this batching and keeps every
required check and the income-before-affordability dependency. Redeploy the BPMN
(the regression fixture does this) before validating the new instructions.
The prompt also enumerates required tool argument names and requires exact context
identifiers and the numeric requested amount. A captured empty `{}` remains a real
argument failure, even if engine-bound variables let a mock service task complete.

- `pytest.ini` here enables MLflow's pytest plugin (`-p mlflow.pytest.plugin`) and live console logging.
- `conftest.py` selects the HTTP tracking server and regression experiment before
  any run opens, caps noisy loggers, and limits judge concurrency to one for Ollama
  (OpenAI defaults to ten). Explicit environment overrides are respected.

### Environment variables

All are optional — each has a working default. `setdefault` semantics mean an externally-provided value (e.g. from CI)
is always respected.

| Variable                                  | Default                                         | Set in                              | Purpose                                                                                                                                                                                                 |
|-------------------------------------------|-------------------------------------------------|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `REGRESSION_ACTIVITY_TIMEOUT`             | `600` (seconds)                                 | `test_mlflow_regression.py`         | Max time to wait for one golden's agentic subprocess run to finish                                                                                                                                      |
| `REGRESSION_GOLDEN_MATCH_THRESHOLD`       | `0.7`                                           | `fluxnova_mlflow_dataset.scorers`   | Min `matches_golden` judge score (0.0–1.0) counted as a "yes" verdict                                                                                                                                   |
| `REGRESSION_EVIDENCE_CITATION_THRESHOLD`  | `0.7`                                           | `test_mlflow_regression.py`         | Min `evidence_citation` judge score (0.0–1.0) counted as a pass                                                                                                                                         |
| `LLM_JUDGE_PROVIDER`                      | `openai`                                       | `fluxnova_mlflow_dataset.scorers`   | Provider for semantic/auxiliary judges; Ollama defaults to `gemma4:e2b` |
| `DECISION_QUALITY_MODEL`                  | `openai:/gpt-4.1-mini` for OpenAI               | `fluxnova_mlflow_dataset.scorers`   | Full URI override for regression/listener semantic judging; worker has its own explicit `EVAL_SERVICE_JUDGE_MODEL` |
| `OPENAI_API_KEY`                          | none                                            | read by `litellm`/MLflow            | Required for OpenAI; semantic judge is `gpt-4.1-mini`, auxiliary judges `gpt-4o-mini`, agent `gpt-4o` |
| `MLFLOW_GENAI_EVAL_MAX_WORKERS`           | `1` with `LLM_JUDGE_PROVIDER=ollama`, else `10` | `conftest.py`                       | Judge-call concurrency; capped to 1 only for the single-instance local Ollama judge                                                                                                                     |
| `MLFLOW_TRACKING_URI`                     | `http://localhost:5001` (`default_server_tracking_uri`) | `conftest.py`                 | HTTP tracking server; avoids direct database/schema and container-local artifact access |
| `MLFLOW_HOST` / `MLFLOW_PORT`             | `localhost` / `5001`                            | `default_server_tracking_uri`       | Host endpoint used when no explicit tracking URI is exported |
| `MLFLOW_EXPERIMENT_NAME`                  | `EVAL_SERVICE_EXPERIMENT_NAME` or `fluxnova-loanAssessmentEvalProcess` | `conftest.py` | Evaluation experiment override; raw traces keep the collector target |
| `REGRESSION_REPORT_DIR`                   | `local-dev/.mlflow/reports`                     | `test_mlflow_regression.py`          | Local JSON report root; each run gets a separate directory |
| `FLUXNOVA_USERNAME` / `FLUXNOVA_PASSWORD` | none                                            | read by `test_mlflow_regression.py` | Credentials for the Fluxnova engine / mock workers                                                                                                                                                      |

> **Note:** `REGRESSION_GOLDEN_MATCH_THRESHOLD` is read inside the shared `fluxnova-mlflow-dataset` package (the
> `matches_golden` scorer), not in this directory — it keeps the `REGRESSION_` prefix so all knobs for a regression run
> are discoverable by name.
