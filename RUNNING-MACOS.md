# Run and validate the Fluxnova demo on macOS

Follow these steps from the repository root in Terminal. zsh is fine. The default
demo uses OpenAI (`gpt-4o` agent and `gpt-4o-mini` judges), so Ollama and gateway
configuration are optional. Allow time for initial image pulls and Python builds.

## 1. Install prerequisites and start Podman

Install Podman (Podman Desktop is convenient) and Python 3.11+. With Homebrew:

```bash
brew install podman python@3.11
podman --version
```

If a Podman machine already exists, use it:

```bash
podman machine list
podman machine start
podman info --format '{{.Host.Arch}}'
```

For a fresh Apple Silicon setup, AppleHV supports Rosetta for the current AMD64
Fluxnova image. Install Rosetta if needed (`softwareupdate --install-rosetta`), then
create a machine using that provider:

```bash
export CONTAINERS_MACHINE_PROVIDER=applehv
podman machine init --cpus 4 --memory 8192 --disk-size 60
podman machine start
```

Use that provider environment in subsequent terminals when managing the machine.
Keep an existing machine if its x86 execution works; the test below establishes
that without running the demo. On an Intel Mac use the normal machine defaults.
The suggested VM allocation is a starting point, not a measured minimum.

## 2. Verify engine image execution support

The engine image is currently AMD64-only. On Apple Silicon check that the VM can
execute x86 containers:

```bash
podman run --rm --platform linux/amd64 docker.io/library/alpine:3.21 uname -m
podman pull --platform linux/amd64 ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.2.0
```

**Expected:** the first command prints `x86_64`; the engine image pulls successfully.
An `exec format error` means the VM's emulation needs configuration before continuing.
Check the selected provider/Rosetta setting in Podman Desktop. Other demo images
run natively on Apple Silicon.

## 3. Install the Python development environment

```bash
PYTHON=python3.11 ./setup.sh
source .venv/bin/activate
python --version
fluxnova-run --help
eval-service-worker --help
eval-trace-listener --help
mlflow-judges --help
```

**Expected:** Python 3.11+ and CLI usage text. All four project packages are editable.
If Homebrew's `python3.11` is not on PATH, pass its full path as `PYTHON`.

## 4. Configure the demo

For a new checkout only:

```bash
cp local-dev/.env.example local-dev/.env
open -e local-dev/.env
```

Set `OPENAI_API_KEY` to your key. Keep:

```dotenv
FLUXNOVA_PLATFORM=linux/amd64
LLM_JUDGE_PROVIDER=openai
EVAL_SERVICE_JUDGE_MODEL=openai:/gpt-4o-mini
```

macOS defaults to bridge networking. If reusing an old `.env`, remove or change
`DEV_NETWORK_MODE=host`, use the image versions in `.env.example`, add the judge
model setting above, and remove obsolete `MLFLOW_EXPERIMENT_ID`. Preserve your key.
No fixed experiment ID or gateway endpoint is needed.

If port `5000` is already in use (often AirPlay Receiver), set `MLFLOW_PORT=5001`.
You may similarly change `FLUXNOVA_PORT`, `POSTGRES_PORT`, `PROMETHEUS_PORT` or
`GRAFANA_PORT`. Ensure the `.env` has
`FLUXNOVA_URL=http://localhost:${FLUXNOVA_PORT}/engine-rest` for host runner access.

Load the host environment in each terminal that runs Python tools:

```bash
set -a
source local-dev/.env
set +a
```

## 5. Start the infrastructure

For pods created with the old scripts, first run `./local-dev/pods-down.sh` to
recreate their configuration; this preserves databases and artifacts.

```bash
./local-dev/pods-up.sh postgres mlflow fluxnova
podman pod ps
podman ps
curl -fsS "http://localhost:${MLFLOW_PORT:-5000}/version"
curl -fsS "${FLUXNOVA_URL}/engine"
podman exec mlflow python -c "from pathlib import Path; print(Path('/mlflow-runtime/headers.yaml').read_text())"
```

**Expected:** three running pods, MLflow `3.16.0`, an engine list containing
`default`, and a header map such as `{"x-mlflow-experiment-id": "1"}`. The actual
ID can be any number; it is created/resolved automatically.

If startup fails, inspect the indicated container:

```bash
podman logs postgres
podman logs mlflow
podman logs fluxnova
podman logs otel-collector
```

## 6. Start evaluation and dashboards

```bash
./local-dev/pods-up.sh eval-service eval-listener observability
podman ps
open "http://localhost:${MLFLOW_PORT:-5000}"
open "http://localhost:${GRAFANA_PORT:-3000}"
```

**Expected:** the worker, listener, Prometheus and Grafana stay running. First-time
worker/listener image builds install Python dependencies. No MLflow Gateway setup
is required for this configuration.

## 7. Run the basic loan-assessment demo

```bash
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

**Expected:** BPMN deployment, a printed process instance ID, and process completion.
Save the ID. The mock workers provide the downstream service responses; the agent
still makes real model calls. In Fluxnova Cockpit (login `demo` / `demo`) inspect
the completed process/history at `http://localhost:8080` (or your overridden port).

## 8. Validate traces, assessments and metrics

1. In MLflow open the experiment named by `EVAL_SERVICE_EXPERIMENT_NAME`
   (default **fluxnova-loanAssessmentEvalProcess**).
2. Open **Traces**. Wait for collector export and the listener's polling cycle.
   Find the completed agent trace, including `invoke_agent`, `chat` and
   `execute_tool` spans. The basic and eval workflows both export to this experiment.
3. Confirm the trace has evaluation assessments, including `decision_quality`,
   `evidence_citation` and deterministic tool checks. A service merely running
   does not establish that scoring succeeded. Inspect listener output if needed:
   ```bash
   podman logs --tail 80 eval-trace-listener
   ```
4. Check the metrics pipeline:
   ```bash
   curl -fsS "http://localhost:${OTEL_METRICS_PORT:-8889}/metrics" | grep '^gen_ai_'
   open "http://localhost:${PROMETHEUS_PORT:-9090}/targets"
   ```
   **Expected:** GenAI sample lines after a run, and the `otel-collector` target **UP**.
5. In Grafana open **Fluxnova → Fluxnova GenAI Metrics**, select a recent time
   range, and confirm token usage, latency and tool/inference counts appear.

If the workflow runs but no trace appears, check collector logs and the generated
MLflow header map. If metrics are empty, wait at least one export/scrape cycle.
Include both logs when reporting networking/export failures; do not count an HTTP
health check alone as end-to-end validation.

## 9. Run the in-process evaluation demo

In a **second terminal**, from the repository root, start persistent mock workers
and leave them running while the asynchronous evaluation/reporting steps finish:

```bash
source .venv/bin/activate
set -a
source local-dev/.env
set +a
fluxnova-run-mock-workers fluxnova-runner/config/loan-assesment-eval.yml
```

Back in the original terminal:

```bash
fluxnova-run fluxnova-runner/config/loan-assesment-eval.yml
podman logs --tail 80 eval-service-worker
```

**Expected:** the runner returns after the loan-assessment Call Activity finishes.
The worker then scores that child run and completes the parent evaluation task.
Allow for asynchronous trace export and judging after the runner returns.

In Cockpit inspect the parent process: `evalPassed` and `evalRationale` should be
present, and the process should progress through the evaluation gateway. A failed
evaluation routes to human review; a pass proceeds toward reporting/approval review.
The workflow may remain at a human task, which is expected. Confirm the worker
logged a completed task rather than an incident, and inspect its MLflow assessments.
After checking the process, stop the second terminal's mock workers with **Ctrl+C**.
Keeping them separate avoids stopping the report mock when the runner returns at
the Call Activity boundary.

## 10. Run unit tests and the live regression gates

Run the package suites separately:

```bash
python -m pytest fluxnova-runner/tests -q
python -m pytest fluxnova-mlflow-dataset/tests -q
python -m pytest eval-service-worker/tests -q
python -m pytest eval-trace-listener/tests -q
python -m pytest local-dev/tests -q
python -m pytest regression -v -rs
```

**Expected:** unit tests pass; all four live regression gates execute and pass.
Inspect the separate **fluxnova-loanAssessmentProcess-regression** MLflow experiment.
Skipped regression tests mean missing infrastructure, not successful validation.
LLM-driven gates can fail because of agent output; distinguish scored failures
from connectivity/authentication failures before retrying or changing code.

## 11. Validate persistence and stop

Record a trace ID and confirm it remains after recreation:

```bash
./local-dev/pods-down.sh
./local-dev/pods-up.sh
open "http://localhost:${MLFLOW_PORT:-5000}"
```

**Expected:** the prior trace/assessments and experiment remain, and a new workflow
also exports successfully. The experiment ID should be reused. Prometheus/Grafana
runtime storage is ephemeral; the dashboard is provisioned again automatically.

Finish with:

```bash
./local-dev/pods-down.sh
podman machine stop
```

Use `./local-dev/pods-down.sh --delete-data` only when deliberately resetting local
demo databases and artifacts. Normal shutdown preserves them.

## Record validation results

Capture macOS version/CPU, Podman version, VM provider, emulation smoke result,
configured ports, and pass/fail for steps 5–11 in
[issue #21](https://github.com/ScottLogic/fluxnova-eval-demo/issues/21). These changes
include Apple Silicon dependency installation, unit/startup checks and image
manifest checks; the full stack and Intel Mac/Windows runs still need local validation.

For host debugging, Compose, Ollama or the Windows host-network fallback, see
[local-dev/README.md](local-dev/README.md).
