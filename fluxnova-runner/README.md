# fluxnova-runner

A standalone service that deploys a BPMN workflow to Fluxnova, starts a process instance with configurable input
variables, optionally drives mock external-task workers to stand in for real service-task backends, and polls until
the run (or one named activity within it) completes. See the repo root [`README.md`](../README.md)'s "Overview"/
"Architecture" sections for how this fits into the wider pipeline.

Deploy/start/run concerns only — **no reporting or evaluation**. Once a run completes, its trace is persisted in
MLflow and the `eval-trace-listener` service (or `eval-service-worker`) scores it; `fluxnova-runner` itself doesn't
read anything back beyond polling for completion.

## Install

```bash
pip install -e .            # into the shared venv (repo-root .venv), or your own
pip install -e ".[dev]"     # + pytest/ruff for running the test suite
```

Installs two console-script entry points: `fluxnova-run` and `fluxnova-run-mock-workers`.

## Config

Reads a workflow YAML config file from [`config/`](config) (e.g. `fluxnova-runner/config/loan-assesment.yml`) — see
the repo root README's "Config file" section for the full field reference. `RunnerConfig.from_file` only reads the
fields it needs and silently ignores the rest (`subprocess_id`, `available_tools`, `mlflow_dataset`, etc. — used by
the eval services), so the same file works unchanged for both:

| Field             | Required | Description                                                                   |
|-------------------|----------|-------------------------------------------------------------------------------|
| `fluxnova_url`    | Yes      | Fluxnova engine REST base URL; exported `FLUXNOVA_URL` overrides it for local ports |
| `bpmn_path`       | Yes      | Path to the `.bpmn` file — resolved relative to the repo root if not absolute |
| `process_key`     | Yes      | The `id` attribute on `<process>` in the BPMN                                 |
| `deployment_name` | Yes      | Human-readable deployment name shown in Cockpit                               |
| `variables`       | No       | Initial process variables (plain `key: value` pairs)                          |
| `mock_workers`    | No       | `{topic: {output variables}}` — see "Mock workers" below                      |

## Usage

```bash
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

Deploys the BPMN, starts a process instance with the config's `variables`, starts one mock external-task worker
thread per `mock_workers` topic (if `--with-mock-workers` is given), then polls until the process completes and
prints the process instance ID.

```bash
fluxnova-run --skip-deploy fluxnova-runner/config/loan-assesment.yml        # BPMN already deployed — skip the deploy step
fluxnova-run fluxnova-runner/config/loan-assesment.yml                       # no mock workers — needs real service-task backends
fluxnova-run --wait-for-activity AdHocSubProcess_LoanAssessmentAgent fluxnova-runner/config/loan-assesment-eval.yml
```

`--wait-for-activity ACTIVITY_ID` returns as soon as that one BPMN activity finishes, instead of waiting for the
whole process instance — useful when a downstream step (e.g. `eval-service-worker`'s service task) shouldn't block
the run from being considered "done" for the runner's purposes.

Set `FLUXNOVA_USERNAME`/`FLUXNOVA_PASSWORD` env vars if the engine has auth enabled; both are read from the
environment, never from the config file.

### Mock workers standalone

```bash
fluxnova-run-mock-workers fluxnova-runner/config/loan-assesment.yml
```

Starts the same mock external-task workers as `--with-mock-workers` above, without deploying or starting a process
— useful for keeping workers running independently (e.g. against multiple runs started elsewhere), or for testing
worker behaviour in isolation. Blocks until interrupted (Ctrl+C).

## Tests

```bash
pytest tests
```
