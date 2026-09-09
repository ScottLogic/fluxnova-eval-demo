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

Installs two console-script entry points from this package: `mlflow-eval` and `mlflow-judges`
(`fluxnova-run`/`fluxnova-run-mock-workers` come from the sibling `fluxnova-runner` install).

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

> **Note:** `fluxnova/config.py` defines its own `ExpectedToolRule` (parsing/evaluating the same `$var == value`
> syntax) independently of `fluxnova_mlflow_dataset.tools.ExpectedToolRule` — the two implementations are
> near-identical but not shared. See [`fluxnova-mlflow-dataset/README.md`](../fluxnova-mlflow-dataset/README.md) for
> the rule syntax reference.

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
Gateway. This is what `mlflow-judges` (below) registers/starts.

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

## Tests

```bash
pytest tests
```

`harness/tests/` has one suite: `test_mlflow_regression.py`, an **MLflow agent regression test**
(MLflow's [regression-testing pattern](https://mlflow.org/docs/latest/genai/eval-monitor/regression-testing/)). Unlike
`mlflow-eval` (which re-scores already-recorded runs), this test actually drives the live
loan-assessment agent end-to-end — once per golden scenario in `datasets/loan-assessment/goldens.json` — and asserts
each real output still satisfies the shared `decision_quality` judge. It's a gating check, not a coverage suite: the
intent is to catch a behavioural regression before it ships, not to exercise this codebase's own logic.

Results are recorded to the shared PostgreSQL-backed MLflow tracking store, under a dedicated
`fluxnova-loanAssessmentProcess-regression` experiment (kept separate from real recorded agent runs).

**Prerequisites:** the full live stack must be up (Fluxnova engine, Postgres, OTel Collector, MLflow, Ollama — see
[`local-dev/README.md`](../local-dev/README.md)) — the test skips cleanly if the engine or tracking store isn't
reachable rather than failing.

```bash
pytest tests/test_mlflow_regression.py -v
```

The logic it depends on most heavily otherwise (record shaping, trace reading, collection, shared judge/scorer
definitions) is covered by [`fluxnova-mlflow-dataset`](../fluxnova-mlflow-dataset/README.md#tests)'s own test suite
instead; the harness-specific code (`WorkflowConfig` loading/validation, the `mlflow_eval` scorers and
CLIs) is currently exercised manually rather than under pytest.
