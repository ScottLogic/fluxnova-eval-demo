# regression

The end-to-end **MLflow agent regression suite** for the Fluxnova loan-assessment agent — the project's gating check
against behavioural regressions. It lives at the repo root (rather than inside any one package) because it drives the
whole stack: it depends on `fluxnova-runner` (to run the live agent) and `fluxnova-mlflow-dataset` (for the shared
judges/scorers).

## What it does

`test_mlflow_regression.py` has **one test per golden**: `test_agent_passes_golden` is parametrized over every scenario
in [`datasets/loan-assessment/goldens.json`](../datasets/loan-assessment/goldens.json), with the golden's
`additional_metadata.scenario` as its test id (e.g. `test_agent_passes_golden[employed-high-fraud-reject]`). Each test:

1. drives the live loan-assessment agent end-to-end once via `fluxnova-runner`;
2. scores that one actual output with **every** gating scorer in a single `mlflow.genai.evaluate()` call;
3. asserts every applicable scorer passed, listing *all* failing scorers (value + rationale) in the failure message.

The gating scorers:

- `decision_quality` — guideline judge: a definitive APPROVE/REJECT backed by cited evidence.
- `matches_golden` — judge: matches the golden's `expected_output` (thresholded at `GOLDEN_MATCH_THRESHOLD`).
- `evidence_citation` — judge: grounds its reasoning in the applicant/tool evidence (a graded 0.0–1.0 score,
  thresholded at `REGRESSION_EVIDENCE_CITATION_THRESHOLD`).
- `fluxnova_mlflow_dataset.scorers.ALL_DETERMINISTIC_SCORERS` — states an APPROVE/REJECT keyword, called exactly the
  tools its applicant profile requires (and none it shouldn't), made no failed tool calls, called tools in the
  expected order, and passed each tool the arguments the BPMN wires up for it. Graded scores must be a full 1.0.

A judge that produces no verdict, or any scorer that errors, fails the golden. A deterministic scorer returning `None`
("not applicable" to this golden's profile, e.g. `no_collateral_check_when_no_collateral` when there is collateral) is
reported as `n/a` and never fails it.

Running the agent once per golden and scoring that one output with every scorer guarantees they all judge the *same*
real (non-deterministic) output, with no cross-test caching. It also means a single scenario can be rerun cheaply with
`pytest -k <scenario>`, and a golden whose agent run times out fails only its own test.

Every scorer's result (`name`, `status` of `passed`/`failed`/`n/a`, `value`, `rationale`) is also written into the
pytest-json-report's per-test `metadata.scorers` via the `json_metadata` fixture, which `ui-api` surfaces so the UI
can show the per-scorer breakdown for each golden.

### Scorers and how the data is retrieved

The regression suite is the only consumer that runs the **LLM judges that need a reference answer or input
variables**, because it has the golden dataset on hand.

| Scorer                            | Type      | Pass rule                                            |
|-----------------------------------|-----------|------------------------------------------------------|
| `decision_quality`                | LLM judge | verdict `yes`                                        |
| `matches_golden`                  | LLM judge | verdict `yes`                                        |
| `evidence_citation`               | LLM judge | score ≥ `REGRESSION_EVIDENCE_CITATION_THRESHOLD`     |
| `ALL_DETERMINISTIC_SCORERS` (~14) | Code      | `true` / score 1.0 (`None` = not applicable)         |

**How the scorer inputs are sourced — with no MLflow trace read.** Every value the scorers need is read straight off
the Fluxnova engine's REST API rather than the run's MLflow trace, and passed to `evaluate()` as a static row:

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
# or a single golden:
pytest regression/test_mlflow_regression.py -v -k employed-high-fraud-reject
```

**Prerequisites:** the full live stack must be up (Fluxnova engine, Postgres, OTel Collector, MLflow — see
[`local-dev/README.md`](../local-dev/README.md)). The suite **skips cleanly** if the engine or tracking store isn't
reachable rather than failing. The LLM-as-judge scorers (`decision_quality`, `matches_golden`, `evidence_citation`)
default to OpenAI, so `OPENAI_API_KEY` must be set in the shell running pytest; set `LLM_JUDGE_PROVIDER=ollama`
instead to judge fully locally (Ollama must then be running with `gemma4:e2b` pulled).

## Configuration

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
