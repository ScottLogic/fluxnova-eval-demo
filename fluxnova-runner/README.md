# fluxnova-runner

A standalone service that deploys a BPMN workflow to Fluxnova, starts a process instance with configurable input
variables, optionally drives mock external-task workers to stand in for real service-task backends, and polls until
the run (or one named activity within it) completes. See the repo root [`README.md`](../README.md)'s "Overview"/
"Architecture" sections for how this fits into the wider pipeline.

Deploy/start/run concerns only — **no reporting or evaluation**. Once a run completes, its trace is persisted in
MLflow. Workflows with Eval service tasks (such as `LoanApprovalProcess_AI.bpmn`) are scored by the
`eval-service-worker` (blocking guardrail) and `eval-async-worker` (non-blocking); `fluxnova-runner` itself doesn't
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
fields it needs and silently ignores unknown fields (`available_tools`, `expected_tools`, `dataset_path`,
`mlflow_dataset`). These are reference/legacy only; no service reads them.

| Field             | Required | Description                                                                   |
|-------------------|----------|-------------------------------------------------------------------------------|
| `fluxnova_url`    | Yes      | Fluxnova engine REST base URL; exported `FLUXNOVA_URL` overrides it for local ports |
| `bpmn_path`       | Yes      | Path to the `.bpmn` file — resolved relative to the repo root if not absolute |
| `process_key`     | Yes      | The `id` attribute on `<process>` in the BPMN                                 |
| `deployment_name` | Yes      | Human-readable deployment name shown in Cockpit                               |
| `additional_bpmn_paths` | No | Extra `.bpmn` files deployed alongside, e.g. a Call Activity's called process |
| `additional_resources`  | No | Other deployable files in the same deployment, e.g. a `.form` referenced by a user task's `camunda:formRef` |
| `variables`       | No       | Initial process variables (plain `key: value` pairs); can include the guardrail inputs `evalMinScore`, `evalRequiredScorers`, `evalSampleRate`, `forceReviewEveryN` |
| `mock_workers`    | No       | `{topic: {output variables}}` — see "Mock workers" below                      |
| `wait_for_activity` | No     | Return when this activity completes; `--wait-for-activity` overrides it       |
| `subprocess_id`   | No       | Ad-hoc subprocess id, used by ui-api for the agent config                     |

`loan_approval_process_ai.yml` is the current workflow.

## Usage

```bash
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

Deploys the BPMN, starts a process instance with the config's `variables`, starts one mock external-task worker
thread per `mock_workers` topic (if `--with-mock-workers` is given), then polls until the process completes and
prints the process instance ID. Before deploying it clears stale external-task locks left by crashed workers.

> **Warning — destructive redeploy.** Unless `--skip-deploy` is given, `fluxnova-run` first deletes every existing
> deployment with the config's `deployment_name`, with cascade. That removes all their process instances, history,
> open user tasks and external tasks. It also restarts the guardrail's every-Nth run count. Use `--skip-deploy` (or
> a different `deployment_name`) to keep earlier runs. ui-api's workflow endpoint does not do this.

```bash
fluxnova-run --skip-deploy fluxnova-runner/config/loan-assesment.yml        # BPMN already deployed — skip the deploy step
fluxnova-run fluxnova-runner/config/loan-assesment.yml                       # no mock workers — needs real service-task backends
fluxnova-run --wait-for-activity CallActivity_LoanAssessmentAgent fluxnova-runner/config/loan-assesment-eval.yml
```

`--wait-for-activity ACTIVITY_ID` returns as soon as that one BPMN activity finishes, instead of waiting for the
whole process instance — useful when a downstream step (e.g. `eval-service-worker`'s service task) shouldn't block
the run from being considered "done" for the runner's purposes. `--timeout SECONDS` (default 600) caps the wait.

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
