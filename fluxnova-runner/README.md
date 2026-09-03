# fluxnova-runner

A standalone service that deploys a BPMN workflow to Fluxnova, starts a process instance with configurable input
variables, optionally drives mock external-task workers to stand in for real service-task backends, and polls until
the run (or one named activity within it) completes. See the repo root [`README.md`](../README.md)'s "Overview"/
"Architecture" sections for how this fits into the wider pipeline.

Deploy/start/run concerns only — **no reporting or evaluation**. Once a run completes, use `mlflow-eval <config>
--collect` (see [`harness/README.md`](../harness/README.md)) to pull it out of MLflow's trace store and record it
into the evaluation dataset; `fluxnova-runner` itself doesn't read anything back beyond polling for completion.

## Install

```bash
pip install -e .            # into the harness venv (harness/.venv), or your own
pip install -e ".[dev]"     # + pytest/ruff for running the test suite
```

Installs two console-script entry points: `fluxnova-run` and `fluxnova-run-mock-workers`.

## Config

Reads the same workflow YAML config file used by `harness` (e.g. `harness/config/loan-assesment.yml`) — see the
repo root README's "Config file" section for the full schema. `RunnerConfig.from_file` only reads the fields it
needs and silently ignores the rest (`subprocess_id`, `available_tools`, `mlflow_dataset`, etc. — used by the
harness's eval tools), so the same file works unchanged for both:

| Field | Required | Description |
|-------|----------|--------------|
| `fluxnova_url` | Yes | Fluxnova engine REST base URL |
| `bpmn_path` | Yes | Path to the `.bpmn` file — resolved relative to the repo root if not absolute |
| `process_key` | Yes | The `id` attribute on `<process>` in the BPMN |
| `deployment_name` | Yes | Human-readable deployment name shown in Cockpit |
| `variables` | No | Initial process variables (plain `key: value` pairs) |
| `mock_workers` | No | `{topic: {output variables}}` — see "Mock workers" below |

## Usage

```bash
fluxnova-run config/loan-assesment.yml --with-mock-workers
```

Deploys the BPMN, starts a process instance with the config's `variables`, starts one mock external-task worker
thread per `mock_workers` topic (if `--with-mock-workers` is given), then polls until the process completes and
prints the process instance ID.

```bash
fluxnova-run --skip-deploy config/loan-assesment.yml        # BPMN already deployed — skip the deploy step
fluxnova-run config/loan-assesment.yml                       # no mock workers — needs real service-task backends
fluxnova-run --wait-for-activity AdHocSubProcess_LoanAssessmentAgent config/loan-assesment-eval.yml
```

`--wait-for-activity ACTIVITY_ID` returns as soon as that one BPMN activity finishes, instead of waiting for the
whole process instance — useful when a downstream step (e.g. `eval-service-worker`'s service task) shouldn't block
the run from being considered "done" for the runner's purposes.

Set `FLUXNOVA_USERNAME`/`FLUXNOVA_PASSWORD` env vars if the engine has auth enabled; both are read from the
environment, never from the config file.

### Mock workers standalone

```bash
fluxnova-run-mock-workers config/loan-assesment.yml
```

Starts the same mock external-task workers as `--with-mock-workers` above, without deploying or starting a process
— useful for keeping workers running independently (e.g. against multiple runs started elsewhere), or for testing
worker behaviour in isolation. Blocks until interrupted (Ctrl+C).

## Fluxnova REST client (`client.py`)

`Client` is a thin wrapper around the subset of the Fluxnova Engine REST API the runner needs:

| Method | Purpose |
|--------|---------|
| `deploy(bpmn_path, deployment_name)` | Upload a BPMN file as a new deployment |
| `start_process(process_key, variables)` | Start a process instance; returns the instance ID |
| `claim_task(task_id, user_id)` / `complete_task(task_id, variables)` | Claim/complete a user task |
| `get_instance(instance_id)` | Return the running instance, or `None` if it has ended |
| `get_history(instance_id)` | Return the historic instance record (always available, even after completion) |
| `get_variables(instance_id)` | Return final variables via the historic variable-instance API |
| `wait_for_completion(instance_id, poll_interval, timeout)` | Block until the instance finishes; returns final variables; raises `ApiError`/`TimeoutError` on failure/timeout |
| `wait_for_activity_completion(instance_id, activity_id, poll_interval, timeout)` | Block until one named activity finishes, regardless of overall instance state |

Plain Python variable values passed to `start_process`/mock-worker completions are wrapped into Camunda's
`{"value": ..., "type": ...}` format automatically (`_to_camunda_vars`; supported types: `str`, `int`, `float`,
`bool` — everything else is serialised as a `String`).

Read-back of full agent-history/report data (joining trace + BPMN + variables) is deliberately **not** this
client's job — that's `fluxnova_mlflow_dataset.fluxnova_client.FluxnovaClient`, used by `mlflow-eval --collect`.

## Mock workers (`mock_workers.py`)

`start_workers(cfg)` subscribes one `ExternalTaskWorker` daemon thread per `mock_workers` topic in the config and
immediately completes each locked task with the configured output variables. A small random jitter (0–0.5s) is
added before completing each task, to avoid `OptimisticLockingException` when multiple parallel tasks in the same
ad-hoc subprocess complete simultaneously and race to update the same execution entity. `run(cfg)` does the same
but blocks (joins the threads) until interrupted — this is what `fluxnova-run-mock-workers` calls.

## Tests

```bash
pytest tests
```

## Files

| File | Purpose |
|------|---------|
| `src/fluxnova_runner/config.py` | `RunnerConfig` — loads the subset of the workflow YAML this service needs |
| `src/fluxnova_runner/client.py` | `Client` — Fluxnova REST API wrapper (deploy/start/poll) |
| `src/fluxnova_runner/mock_workers.py` | Mock external-task worker threads (`start_workers`/`run`) |
| `src/fluxnova_runner/main.py` | `fluxnova-run` CLI entry point |
| `tests/test_client.py` | Unit tests for `RunnerConfig`, `Client`, and the mock-worker helpers |
