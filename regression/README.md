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
  tools its applicant profile requires (and none it shouldn't), made no failed tool calls, called tools in the
  expected order, and passed each tool the arguments the BPMN wires up for it.
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

The regression suite is the only consumer that runs the **LLM judges that need a reference answer or input
variables**, because it has the golden dataset on hand.

| Scorer                            | Type          | Gating test                                   |
|------------------------------------|---------------|-----------------------------------------------|
| `decision_quality`                 | LLM judge     | `test_agent_reaches_evidence_backed_decision` |
| `matches_golden`                   | LLM judge     | `test_agent_matches_golden_decisions`         |
| `ALL_DETERMINISTIC_SCORERS` (~14)  | Code          | `test_agent_passes_deterministic_checks`      |
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
pytest regression -v
# or a single test:
pytest regression/test_mlflow_regression.py -v
```

**Prerequisites:** the full live stack must be up (Fluxnova engine, Postgres, OTel Collector, MLflow — see
[`local-dev/README.md`](../local-dev/README.md)). The suite **skips cleanly** if the engine or tracking store isn't
reachable rather than failing. The LLM-as-judge scorers (`decision_quality`, `matches_golden`, `evidence_citation`)
default to OpenAI, so `OPENAI_API_KEY` must be set in the shell running pytest; set `LLM_JUDGE_PROVIDER=ollama`
instead to judge fully locally (Ollama must then be running with `gemma4:e2b` pulled).

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

- `pytest.ini` here enables MLflow's pytest plugin (`-p mlflow.pytest.plugin`) and live console logging.
- `conftest.py` points `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME` at the shared store + regression experiment
  before any run opens, caps noisy third-party loggers, and serialises judge calls (`MLFLOW_GENAI_EVAL_MAX_WORKERS=1`).

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
| `MLFLOW_TRACKING_URI`                     | shared Postgres store (`default_tracking_uri`)  | `conftest.py`                       | Where runs/assessments are recorded                                                                                                                                                                     |
| `MLFLOW_EXPERIMENT_NAME`                  | `fluxnova-loanAssessmentProcess-regression`     | `conftest.py`                       | Experiment the regression runs land in                                                                                                                                                                  |
| `FLUXNOVA_USERNAME` / `FLUXNOVA_PASSWORD` | none                                            | read by `test_mlflow_regression.py` | Credentials for the Fluxnova engine / mock workers                                                                                                                                                      |

> **Note:** `REGRESSION_GOLDEN_MATCH_THRESHOLD` is read inside the shared `fluxnova-mlflow-dataset` package (the
> `matches_golden` scorer), not in this directory — it keeps the `REGRESSION_` prefix so all knobs for a regression run
> are discoverable by name.
