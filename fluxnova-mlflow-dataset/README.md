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
pip install -e .            # into the shared venv (repo-root .venv), or your own
pip install -e ".[dev]"     # + pytest/ruff for running the test suite
```

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

- `harness/src/mlflow_eval/main.py` — offline batch evaluation, called with a direct `"ollama:/gemma4:e2b"`-style URI.
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
