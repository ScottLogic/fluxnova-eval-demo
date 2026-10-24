# fluxnova-mlflow-dataset

A small shared library providing the record-shaping/read/write logic and scorer/judge definitions used by
the Fluxnova eval services (`eval-service-worker`, `eval-trace-listener`, and the `regression/` suite), plus the
`mlflow-judges` CLI for toggling automatic (online) evaluation on/off. See the repo root [`README.md`](../README.md)'s
"Overview"/"Architecture" sections for how this fits into the wider pipeline.

Keeping this logic in one standalone, installable package guarantees what gets written matches what gets read/
evaluated — both call sites use the exact same `build_mlflow_record`/`MlflowTraceReader`/`decision_quality_judge`
rather than two copies that could drift apart.

**What it provides:**

- **Trace reading** (`MlflowTraceReader`) — reads `gen_ai.*` semantic-convention span data (`invoke_agent`,
  `execute_tool`, `chat`) straight out of MLflow's trace store, replacing the old bespoke `fluxnova_listener` OTLP
  receiver now that the OTel Collector exports traces directly to MLflow.
- **Record shaping/read/write** (`store.py`) — builds MLflow evaluation-dataset records from agent-history data and
  reads/writes the persistent PostgreSQL-backed dataset, idempotently.
- **Shared judge/scorer definitions** (`scorers.py`) — the `decision_quality` `Guidelines` judge and a set of
  deterministic, value-based scorers, defined once so the eval services (`eval-service-worker`,
  `eval-trace-listener`) and the regression suite never disagree on what "good" means.

## Install

```bash
pip install -e .            # into the shared venv (repo-root .venv), or your own
pip install -e ".[dev]"     # + pytest/ruff for running the test suite
```

This installs the `mlflow-judges` console script (see below).

## `mlflow-judges`: toggling automatic (online) evaluation

```bash
mlflow-judges --experiment fluxnova-loanAssessmentProcess start --sample-rate 0.1
mlflow-judges --experiment fluxnova-loanAssessmentProcess stop
mlflow-judges --experiment fluxnova-loanAssessmentProcess status
```

Registers/starts/stops/inspects `automatic_judges()` against a target experiment using MLflow's
`Scorer.register()`/`.start()`/`.stop()` — once started, the MLflow server scores a sampled fraction of new traces
automatically, with no code needing to run continuously. `--tracking-uri` (default `http://localhost:5000`) **must**
be the running server's HTTP(S) address, not a direct `postgresql://...` path, since gateway-backed judges route
through that server process — see [`local-dev/README.md`](../local-dev/README.md)'s "MLflow AI Gateway endpoint for
automatic evaluation judges" section for the one-off endpoint setup this depends on. `--filter-string` on `start`
restricts which traces get sampled (e.g. to exclude EDD regression runs).

## MLflow evaluation dataset: schema quirks worth knowing

`store.py`'s `build_mlflow_record`/`write_to_mlflow_dataset` work around two non-obvious constraints in
`EvaluationDataset.merge_records`:

- **Reserved key avoidance.** MLflow classifies a record's `inputs` dict as either "trace" (any keys) or "session"
  (only from `{goal, persona, context, simulation_guidelines}`, for multi-turn agent simulation) and forbids mixing
  "session" identifier keys with custom ones. To stay in the permissive "trace" bucket, records use `agent_goal`
  instead of the reserved `goal` key.
- **Empty-dataset write bug.** `write_to_mlflow_dataset` calls `_reset_records_cache_if_empty` before the first
  write to a brand-new dataset — see the docstring on that function for the full explanation of the
  `has_records()`/`IndexError` bug it works around. Without it, the very first `merge_records` call on a fresh
  dataset crashes.

`dataset_name_for`/`experiment_name_for`/`tracking_uri_for` resolve the dataset name (defaults to the experiment
name), experiment name (defaults to `fluxnova-<process_key>`), and tracking URI (defaults to the local-dev
PostgreSQL store, read from `POSTGRES_HOST`/`POSTGRES_PORT`/`MLFLOW_POSTGRES_*` env vars) — each overridable so a
workflow config can point at a different dataset/experiment/store without any code changes.

## `expected_tools` rule syntax

Shared by `store.build_mlflow_record` (records which tools *should* have been called) and the
`tool_correctness`/`tool_argument_correctness` scorers. A rule is a display tool-name plus an optional GitLab
CI-style `if` condition evaluated against a run's input variables:

```yaml
- tool: Check Credit Score                       # always expected
- tool: Verify Employment
  if: '$applicantType == "EMPLOYED"'             # only expected when this holds
```

Operators: `==`/`!=`. Values: quoted strings, `true`/`false`, or integers. See the repo root README's
"`expected_tools` rule syntax" section for the full reference table.

> **Note:** `fluxnova-runner`'s `RunnerConfig` and the eval scorers both build on this `ExpectedToolRule`
> (imported from `fluxnova_mlflow_dataset.tools`), so the rule parsing/evaluation lives in a single place.

## Shared judge/scorer definitions: `scorers.py`

`decision_quality_judge(model)` builds the one `Guidelines` judge (`DECISION_QUALITY_NAME` /
`DECISION_QUALITY_GUIDELINES`) used identically by:

- the regression suite (`regression/`) — called with a direct `"ollama:/gemma4:e2b"`-style URI.
- `eval-service-worker` — synchronous per-run scoring, using a direct provider URI in the local demo or a `"gateway:/<endpoint>"` URI (required for
  anything routed through the MLflow AI Gateway).

`DETERMINISTIC_SCORERS` (`required_tools_called`, `no_tool_errors`, `definitive_decision_stated`) are non-LLM checks
used by `eval-service-worker`, `eval-trace-listener` and the regression suite. They know nothing about tracing:
each reads plain values from MLflow's standard `inputs`/`outputs` columns (the canonical shape
`{"input_variables", "tool_calls": [{"name", "status", "arguments"}], "iterations"}` — see
`traces.scorer_inputs_from_trace`). Each caller extracts those values from whatever source suits it — the eval
services from the run's MLflow trace (`scorer_inputs_from_trace(trace)`), the regression suite from the live run's
process variables — and passes them via `mlflow.genai.evaluate(data=[{"trace": trace, "inputs": ..., "outputs": ...}],
scorers=[...])`. When a `trace` column is included, MLflow still logs every scorer's `Feedback` back onto that same
real trace (regardless of which columns the scorer reads), grouped under one Evaluation Run.

> **Note:** `required_tools_called`'s tool-call rules (`_ALWAYS_REQUIRED_TOOLS` + the `_expected_tools_for` branching
> on `applicantType`/`hasCollateral`) are a hardcoded mirror of `fluxnova-runner/config/loan-assesment-eval.yml`'s
> `expected_tools` list, kept in sync manually rather than read from that YAML at runtime — this is deliberate (see
> the module's comment) to keep callers free of any BPMN/YAML config read, at the cost of
> needing a manual update here if that BPMN's tool set/rules ever change.

## Tests

```bash
pytest tests
```
