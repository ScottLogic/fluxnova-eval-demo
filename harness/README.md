# harness

The evaluation harness (MLflow) for Fluxnova agentic workflows — the "evaluate" side of the pipeline. It
reads a workflow YAML config, resolves completed agentic subprocess runs (via `fluxnova-mlflow-dataset`), and scores
them with the `mlflow-eval` suite. See the repo root [`README.md`](../README.md) for the full picture
(architecture diagram, first-time setup, end-to-end walkthrough) — this README covers the code layout and APIs
specific to this directory.

- **`mlflow-eval`** (`src/mlflow_eval/`) — the evaluation suite (judge model `gemma4:e2b`). Scores agent-history data
  with `mlflow.genai.evaluate` scorers; results are browsable in the MLflow UI. Can evaluate a single ad-hoc report, a
  single previously recorded run (by process instance ID), or every recorded run at once — optionally collecting
  newly-completed runs first.

## Install

All three of this repo's Python packages install editable into one shared venv under `.venv` at the repo root. Run the
setup script from the repo root (see the root README's "First time setup" for the full sequence):

```bash
./setup.sh
source .venv/Scripts/activate   # or .venv/bin/activate on macOS/Linux
```

It creates `.venv` and runs `pip install -e "harness[dev]" -e "fluxnova-mlflow-dataset[dev]" -e "fluxnova-runner[dev]"`.

Installs the `mlflow-eval` console-script entry point from this package
(`fluxnova-run`/`fluxnova-run-mock-workers` come from the sibling `fluxnova-runner` install, and `mlflow-judges` from
the sibling `fluxnova-mlflow-dataset` install).

## Config: `fluxnova.config.WorkflowConfig`

`WorkflowConfig.from_file(path)` loads a workflow YAML file, validates it against
`fluxnova/workflow-config.schema.json` (raising `ValueError` with the schema's message on failure), and resolves
`bpmn_path`/`dataset_path` relative to the repo root. See the root README's "Config file" section for the full
field reference and an [example](config/loan-assesment.yml); in brief:

| Field | Required | Description |
|-------|----------|--------------|
| `fluxnova_url`, `bpmn_path`, `process_key`, `deployment_name` | Yes | Same as `fluxnova-runner`'s `RunnerConfig` |
| `subprocess_id` | For `--collect` | BPMN element ID of the ad-hoc subprocess containing the LLM agent |
| `variables`, `mock_workers`, `user_tasks` | No | Initial variables / mock worker & user-task completions |
| `dataset_path` | No | Path to the golden-scenario JSON dataset (`datasets/loan-assessment/goldens.json`) |
| `available_tools` | No | `{BPMN service-task element ID: display name}` |
| `expected_tools` | No | Ordered list of `{tool, if}` rules — see root README's "`expected_tools` rule syntax" |
| `mlflow_dataset` | No | `{enabled, name, tracking_uri, also_write_json_report, experiment_name}` — see `MlflowDatasetConfig` |

> **Note:** `fluxnova/config.py` reuses `fluxnova_mlflow_dataset.tools.ExpectedToolRule` (rather than defining its
> own) for parsing/evaluating the `$var == value` syntax. See
> [`fluxnova-mlflow-dataset/README.md`](../fluxnova-mlflow-dataset/README.md) for the rule syntax reference.

`fluxnova/mlflow_dataset.py` adapts `fluxnova-mlflow-dataset`'s `build_mlflow_record`/`write_to_mlflow_dataset`/etc.
to accept a `WorkflowConfig` directly, so `mlflow_eval.main`'s call sites don't need to unpack `config.mlflow_dataset`
fields by hand at every call site.

## `mlflow-eval`: the primary evaluation suite

```bash
mlflow-eval config/loan-assesment.yml --instance-id <processInstanceId>   # one previously recorded run
mlflow-eval config/loan-assesment.yml --all                               # every recorded run for this process_key
mlflow-eval config/loan-assesment.yml --collect --all                     # collect newly-completed runs first, then evaluate
mlflow-eval config/loan-assesment.yml --collect                           # collect only, don't evaluate
```

`--collect` calls `fluxnova_mlflow_dataset.collect_new_runs` (requires `subprocess_id` in the config) to pull
newly-completed runs out of MLflow's trace store into the persistent dataset before evaluating — see
[`fluxnova-mlflow-dataset/README.md`](../fluxnova-mlflow-dataset/README.md) for how collection itself works.
`mlflow-eval` only ever evaluates runs already present in that dataset; without `--collect`, `--instance-id`/`--all`
just read it back.

Results are written to the configured MLflow tracking store (PostgreSQL by default — see
`local-dev/services/postgres-up.sh`) and a metrics summary is printed to the terminal; browse full per-scorer
results (scores, rationales, inputs/outputs) in the MLflow UI.

**Scorers** (`src/mlflow_eval/main.py`) — code checks plus two flavours of LLM judge: a native MLflow `Guidelines`
judge (`decision_quality`, shared with `eval-service-worker` via `fluxnova_mlflow_dataset.scorers`) and a bespoke
`_llm_judge()` helper (litellm-based) for the others. See the root README's
"Evaluation scorers (MLflow)" table for the full list and what each one checks.

`automatic_judges(model=GATEWAY_JUDGE_MODEL)` builds the subset of judges usable for **automatic (online)**
evaluation — currently just `decision_quality`, rebuilt with a `gateway:/<endpoint>` model URI instead of a direct
`ollama:/...` one, since automatic evaluation runs inside the MLflow server itself and must route through the AI
Gateway. This is what the `mlflow-judges` CLI registers/starts.

## `mlflow-judges`: toggling automatic (online) evaluation

The `mlflow-judges` CLI now lives in the sibling `fluxnova-mlflow-dataset` package (co-located with the
`automatic_judges()` definitions it drives) — see
[`fluxnova-mlflow-dataset/README.md`](../fluxnova-mlflow-dataset/README.md#mlflow-judges-toggling-automatic-online-evaluation)
for its usage.

## Tests

The harness has no unit tests of its own. The end-to-end **MLflow agent regression suite** that exercises the
loan-assessment agent lives at the repo root in [`regression/`](../regression/README.md) — see that README for how to
run it and what it asserts.

The logic this harness depends on most heavily (record shaping, trace reading, collection, shared judge/scorer
definitions) is covered by [`fluxnova-mlflow-dataset`](../fluxnova-mlflow-dataset/README.md#tests)'s own test suite
instead; the harness-specific code (`WorkflowConfig` loading/validation, the `mlflow_eval` scorers and
CLIs) is currently exercised manually rather than under pytest.
