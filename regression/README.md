# regression

The end-to-end **MLflow agent regression suite** for the Fluxnova loan-assessment agent — the project's gating check
against behavioural regressions. It lives at the repo root (rather than inside any one package) because it drives the
whole stack: it depends on `fluxnova-runner` (to run the live agent) and `fluxnova-mlflow-dataset` (for the shared
judges/scorers).

## What it does

`test_mlflow_regression.py` follows MLflow's canonical
[`predict_fn` regression-testing pattern](https://mlflow.org/docs/latest/genai/eval-monitor/regression-testing/): for
every golden scenario in [`datasets/loan-assessment/goldens.json`](../datasets/loan-assessment/goldens.json), a
`predict_fn` fixture drives the live loan-assessment agent end-to-end via `fluxnova-runner`, and
`mlflow.genai.evaluate()` scores the agent's *actual* output. Four gating tests:

- `test_agent_reaches_evidence_backed_decision` — the output satisfies the shared `decision_quality` guideline judge (a
  definitive APPROVE/REJECT backed by cited evidence).
- `test_agent_matches_golden_decisions` — the output matches the golden's `expected_output` via the shared
  `matches_golden` judge (thresholded at `GOLDEN_MATCH_THRESHOLD`).
- `test_agent_passes_deterministic_checks` — the output/run passes every scorer in
  `fluxnova_mlflow_dataset.scorers.ALL_DETERMINISTIC_SCORERS`: states an APPROVE/REJECT keyword, called exactly the
  tools its applicant profile requires (and none it shouldn't), ends with a plain
  final recommendation line, made no failed tool calls, called tools in the expected
  order, and passed each tool the arguments the BPMN wires up for it.
- `test_agent_cites_gathered_evidence` — the output grounds its reasoning in the applicant/tool evidence, via the
  shared `evidence_citation` judge (a graded 0.0–1.0 score, thresholded at `REGRESSION_EVIDENCE_CITATION_THRESHOLD`).

Each gating test is its own `mlflow.genai.evaluate(predict_fn=predict_fn, scorers=[...])` call, so `@mlflow.test`
records an independent pass/fail per gate.

### One real run per golden, replayed across every gate

`predict_fn` is cached (keyed by the golden's process variables): the first call for a scenario actually drives the
live agent, and every later call — including from the other three gating tests' own `evaluate()` calls — replays that
same cached result rather than re-running the agent. This is a deliberate departure from calling `predict_fn` fresh
each time: the agent is a live, non-deterministic GPT-4o call, and without caching, `decision_quality`,
`matches_golden`, `test_agent_passes_deterministic_checks`, and `evidence_citation` could each be judging a
*different* actual output for the same golden — a scenario could pass one gate and fail another purely from LLM
variance between calls, unrelated to either scorer. Caching guarantees every gate judges the same real output, keeping
scenario-level flakiness attributable to the agent rather than smeared across unrelated tests. The `evaluation_rows`
fixture forces this one real run per golden up front (calling `predict_fn` directly, before any `evaluate()` call), so
every row's `inputs` already carries that run's full scorer data.

### Scorers and how the data is retrieved

Only regression runs `matches_golden`, which needs a reference answer from the
golden dataset. The other judges are also used by the trace-based evaluation services.

| Scorer                            | Type          | Gating test                                   |
|------------------------------------|---------------|-----------------------------------------------|
| `decision_quality`                 | LLM judge     | `test_agent_reaches_evidence_backed_decision` |
| `matches_golden`                   | LLM judge     | `test_agent_matches_golden_decisions`         |
| `ALL_DETERMINISTIC_SCORERS` (14)  | Code          | `test_agent_passes_deterministic_checks`      |
| `evidence_citation`                | LLM judge     | `test_agent_cites_gathered_evidence`          |

**How the scorer inputs are sourced — with no MLflow trace read.** `predict_fn` makes no `mlflow.*` call: a nested
`mlflow.search_traces` inside a `predict_fn` corrupts MLflow's active-trace context and breaks assessment logging. So
every value the deterministic scorers need is read straight off the Fluxnova engine's REST API instead of a trace:

- `outputs` — the agent's *actual* final answer, read from the run's `_agentConversationHistory` process variable
  (`fluxnova_runner.agent_output`).
- `inputs.input_variables` — the applicant-facing variables the golden started the BPMN with.
- `inputs.tool_calls` / `inputs.iterations` — the agent's tool-call history (name, status, arguments) and loop
  iteration count, parsed from the same `_agentConversationHistory` (now enriched with `toolCalls`/`toolResult` per
  turn) plus the `_agentLoopIndex` process variable (`fluxnova_runner.agent_tool_calls`) — the process-variable
  equivalent of what `eval-service-worker`/`eval-trace-listener` read off the OTel trace's `execute_tool` spans.
- `expectations.expected_output` — the golden's reference answer (consumed by `matches_golden`).

This actually runs the agent — it's a gating check, not a coverage suite. Results are recorded to the shared
PostgreSQL-backed MLflow tracking store under a dedicated `fluxnova-loanAssessmentProcess-regression` experiment (kept
separate from real recorded agent runs).

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
   Expected: six live scenarios cached across four passing gates, no artifact-path
   warnings and no skips. Inspect the experiment named by `MLFLOW_EXPERIMENT_NAME`
   (the default name or your `-v2` override), its `regression/*.json` artifacts and
   local report copies. Scored model-quality failures differ from infrastructure
   errors; use the scenario, process ID and rationale before changing a threshold.
6. **Replay captured results**, substituting the run ID printed by the suite:
   ```bash
   python -m regression.calibrate --mode deterministic --report local-dev/.mlflow/reports/<run-id>/deterministic.json
   python -m regression.calibrate --report local-dev/.mlflow/reports/<run-id>/decision_quality.json
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

## Configuration

Every gate now writes `regression/<gate>.json` to its MLflow run and a local copy
under `local-dev/.mlflow/reports/<run-id>/` (`REGRESSION_REPORT_DIR` overrides the
root). Reports contain scenario labels, engine process instance IDs, cached actual
outputs, expectations, tool calls, total inference counts and scorer verdicts/errors/
rationales. Failures list every affected scenario/scorer, rather than stopping at
the first deterministic scorer. Profile-driven not-applicable checks remain skips;
missing applicable verdicts, missing rows and scorer errors fail the gate.

The four gates still reuse one live agent result per golden. Saved reports can be
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
python -m regression.calibrate --report local-dev/.mlflow/reports/<run-id>/decision_quality.json
python -m regression.calibrate --mode deterministic --report local-dev/.mlflow/reports/<run-id>/deterministic.json
```

Judge mode uses model calls, but never starts/deploys a workflow. The built-in suite
has four expected `yes` and four deliberately invalid expected `no` responses; an
all-yes judge fails calibration. Report replay expects `yes` for each recorded
workflow output. `--model` selects an explicit candidate without changing the agent.
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
| `LLM_JUDGE_PROVIDER`                      | `openai` (model `gpt-4o-mini`)                  | `fluxnova_mlflow_dataset.scorers`   | Judge provider for `decision_quality`/`matches_golden`/`evidence_citation`; set to `ollama` (model `gemma4:e2b`) for a fully local fallback                                                             |
| `OPENAI_API_KEY`                          | none                                            | read by `litellm`/MLflow            | Required while `LLM_JUDGE_PROVIDER=openai` (the default) — same key as the BPMN agent's, but a separate model (`gpt-4o-mini` vs. the agent's `gpt-4o`) so the judge never grades a model judging itself |
| `MLFLOW_GENAI_EVAL_MAX_WORKERS`           | `1` with `LLM_JUDGE_PROVIDER=ollama`, else `10` | `conftest.py`                       | Judge-call concurrency; capped to 1 only for the single-instance local Ollama judge                                                                                                                     |
| `MLFLOW_TRACKING_URI`                     | `http://localhost:5001` (`default_server_tracking_uri`) | `conftest.py`                 | HTTP tracking server; avoids direct database/schema and container-local artifact access |
| `MLFLOW_HOST` / `MLFLOW_PORT`             | `localhost` / `5001`                            | `default_server_tracking_uri`       | Host endpoint used when no explicit tracking URI is exported |
| `MLFLOW_EXPERIMENT_NAME`                  | `fluxnova-loanAssessmentProcess-regression`     | `conftest.py`                       | Experiment the regression runs land in                                                                                                                                                                  |
| `REGRESSION_REPORT_DIR`                   | `local-dev/.mlflow/reports`                     | `test_mlflow_regression.py`          | Local JSON report root; each run gets a separate directory |
| `FLUXNOVA_USERNAME` / `FLUXNOVA_PASSWORD` | none                                            | read by `test_mlflow_regression.py` | Credentials for the Fluxnova engine / mock workers                                                                                                                                                      |

> **Note:** `REGRESSION_GOLDEN_MATCH_THRESHOLD` is read inside the shared `fluxnova-mlflow-dataset` package (the
> `matches_golden` scorer), not in this directory — it keeps the `REGRESSION_` prefix so all knobs for a regression run
> are discoverable by name.
