# fluxnova-mlflow-dataset

A small shared library (no CLI of its own) providing the record-shaping/read/write/collect logic used by both
`harness`'s `mlflow_eval` suite and `eval-service-worker`. See the repo root [`README.md`](../README.md)'s
"Overview"/"Architecture" sections for how this fits into the wider pipeline.

Keeping this logic in one standalone, installable package guarantees what gets written matches what gets read/
evaluated — both call sites use the exact same `build_mlflow_record`/`MlflowTraceReader`/`decision_quality_judge`
rather than two copies that could drift apart.

**What it provides:**

- **Collection** (`collect_new_runs`) — an on-demand pre-step (invoked via `mlflow-eval --collect`, not a background
  service) that finds newly-completed agentic subprocess runs directly in MLflow's own trace store, joins that trace
  data with the static BPMN definition and the run's final process variables, and upserts an evaluation-dataset
  record for each one not already present.
- **Trace reading** (`MlflowTraceReader`) — reads `gen_ai.*` semantic-convention span data (`invoke_agent`,
  `execute_tool`, `chat`) straight out of MLflow's trace store, replacing the old bespoke `fluxnova_listener` OTLP
  receiver now that the OTel Collector exports traces directly to MLflow.
- **Record shaping/read/write** (`store.py`) — builds MLflow evaluation-dataset records from agent-history data and
  reads/writes the persistent PostgreSQL-backed dataset, idempotently.
- **Shared judge/scorer definitions** (`scorers.py`) — the `decision_quality` `Guidelines` judge and a set of
  deterministic, trace-only scorers, defined once so the offline `mlflow-eval` suite and the synchronous
  `eval-service-worker` never disagree on what "good" means.

## Install

```bash
pip install -e .            # into the harness venv (harness/.venv), or your own
pip install -e ".[dev]"     # + pytest/ruff for running the test suite
```

## Modules

| Module | Purpose |
|--------|---------|
| `bpmn.py` | `BpmnLookup` — parses a `.bpmn` file once and exposes its statically-defined agent config (system prompt, context variable names, per-tool input/output parameter names, tool display names). |
| `fluxnova_client.py` | `FluxnovaClient` — minimal, read-only Fluxnova REST client. Only `get_variables` (via `/history/variable-instance`, so it works after the instance ends); deploying/starting processes is `fluxnova-runner`'s job. |
| `traces.py` | `MlflowTraceReader` — reads GenAI span data for completed runs out of an MLflow experiment's traces, plus free functions (`final_output_from_spans`, `input_variables_from_spans`, `tool_calls_from_spans`) reused by both the reader and `scorers.py`'s trace-only scorers. |
| `report.py` | `build_agent_report` — composes an `/agent-history`-shaped dict for one process instance by joining `MlflowTraceReader` + `BpmnLookup` + a `VariableReader` (e.g. `FluxnovaClient`). |
| `collect.py` | `collect_new_runs` — finds every newly-completed run for a `subprocess_id` and upserts a dataset record for each, via `build_agent_report` + `store.build_mlflow_record`/`write_to_mlflow_dataset`. |
| `store.py` | Record shaping (`build_mlflow_record`) plus dataset read/write (`get_or_create_dataset`, `record_exists`, `write_to_mlflow_dataset`) and tracking-URI/name resolution helpers. |
| `tools.py` | `ExpectedToolRule` — parses and evaluates the `expected_tools` rule syntax (GitLab CI-style `if` expressions against a run's input variables). |
| `goldens.py` | `load_goldens`/`match_golden` — loads a golden-scenario dataset and matches one to a run by `applicantType`/`hasCollateral`. |
| `scorers.py` | `decision_quality_judge` (the shared `Guidelines` judge) and `DETERMINISTIC_SCORERS` (`required_tools_called`, `no_tool_errors`, `definitive_decision_stated`) — trace-only scorers used by `eval-service-worker`. |

Everything above is re-exported from the package root (`fluxnova_mlflow_dataset/__init__.py`), so callers do
`from fluxnova_mlflow_dataset import collect_new_runs, decision_quality_judge, ...` rather than reaching into
individual modules.

## Collecting completed runs: `collect_new_runs`

```python
from pathlib import Path
from fluxnova_mlflow_dataset import collect_new_runs

results = collect_new_runs(
    tracking_uri="postgresql://mlflow:mlflow@localhost:5432/mlflow",
    fluxnova_url="http://localhost:8080/engine-rest",
    process_key="loanAssessmentProcess",
    subprocess_id="AdHocSubProcess_LoanAssessmentAgent",
    bpmn_path=Path("bpmn/loan-assesment.bpmn"),
    variable_names=["applicantType", "hasCollateral", "requestedAmount"],
    available_tools={"ServiceTask_CreditScoreCheck": "Check Credit Score", ...},
    expected_tool_rules=[...],
    dataset_path=Path("datasets/loan-assessment/goldens.json"),
)
for run in results:
    print(run.process_instance_id, run.dataset_name, run.record_id, run.written)
```

Returns one `CollectedRun` per newly-completed run found (`process_instance_id`, `dataset_name`, `record_id`,
`written`). Idempotent — already-recorded runs (matched by `processInstanceId`) are skipped (`written=False`,
`record_id=None`) rather than re-written, so it's safe to call before every evaluation. The
`trace_reader`/`fluxnova_client`/`bpmn` keyword arguments exist purely for dependency injection in tests; real
callers should leave them unset.

`harness/src/fluxnova/mlflow_dataset.py` is a thin adapter over this package that accepts the harness's
`WorkflowConfig` object directly, so `mlflow_eval.main`'s call sites don't need to unpack config fields by hand.

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

Shared by `store.build_mlflow_record` (records which tools *should* have been called) and the harness's
`tool_correctness`/`tool_argument_correctness` scorers. A rule is a display tool-name plus an optional GitLab
CI-style `if` condition evaluated against a run's input variables:

```yaml
- tool: Check Credit Score                       # always expected
- tool: Verify Employment
  if: '$applicantType == "EMPLOYED"'             # only expected when this holds
```

Operators: `==`/`!=`. Values: quoted strings, `true`/`false`, or integers. See the repo root README's
"`expected_tools` rule syntax" section for the full reference table.

> **Note:** `harness/src/fluxnova/config.py` defines its own near-identical `ExpectedToolRule` (same regex, same
> semantics) for the harness's own config-loading needs (e.g. DeepEval's fixture resolution). The two haven't been
> deduplicated — if the rule syntax ever changes, both copies need updating.

## Shared judge/scorer definitions: `scorers.py`

`decision_quality_judge(model)` builds the one `Guidelines` judge (`DECISION_QUALITY_NAME` /
`DECISION_QUALITY_GUIDELINES`) used identically by:

- `harness/src/mlflow_eval/main.py` — offline batch evaluation, called with a direct `"ollama:/llama3.2"`-style URI.
- `eval-service-worker` — synchronous per-run scoring, called with a `"gateway:/<endpoint>"` URI (required for
  anything routed through the MLflow AI Gateway).

`DETERMINISTIC_SCORERS` (`required_tools_called`, `no_tool_errors`, `definitive_decision_stated`) are trace-only,
non-LLM checks used by `eval-service-worker` — they take MLflow's `trace` parameter directly (not `inputs`/
`outputs`), so `mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])` logs every scorer's `Feedback` back
onto that same real trace, grouped under one Evaluation Run.

> **Note:** `required_tools_called`'s tool-call rules (`_ALWAYS_REQUIRED_TOOLS` + the `_expected_tools_for` branching
> on `applicantType`/`hasCollateral`) are a hardcoded mirror of `harness/config/loan-assesment-eval.yml`'s
> `expected_tools` list, kept in sync manually rather than read from that YAML at runtime — this is deliberate (see
> the module's comment) to keep `eval-service-worker` trace-only with no BPMN/YAML config read, at the cost of
> needing a manual update here if that BPMN's tool set/rules ever change.

## Tests

```bash
pytest tests
```

## Files

| File | Purpose |
|------|---------|
| `src/fluxnova_mlflow_dataset/bpmn.py` | `BpmnLookup` — static agent config parsed from a BPMN file |
| `src/fluxnova_mlflow_dataset/fluxnova_client.py` | Read-only Fluxnova REST client (`get_variables`) |
| `src/fluxnova_mlflow_dataset/traces.py` | `MlflowTraceReader` + free span-reading helpers |
| `src/fluxnova_mlflow_dataset/report.py` | `build_agent_report` — joins trace/BPMN/variable data into one report |
| `src/fluxnova_mlflow_dataset/collect.py` | `collect_new_runs` — the on-demand collection pre-step |
| `src/fluxnova_mlflow_dataset/store.py` | Record shaping + MLflow evaluation-dataset read/write |
| `src/fluxnova_mlflow_dataset/tools.py` | `ExpectedToolRule` parsing/evaluation |
| `src/fluxnova_mlflow_dataset/goldens.py` | Golden-scenario loading/matching |
| `src/fluxnova_mlflow_dataset/scorers.py` | Shared `decision_quality` judge + deterministic trace-only scorers |
| `tests/` | Unit tests (`pytest tests`) — one file per module above |
