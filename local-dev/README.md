# Local development with Podman: macOS, Windows and Linux

The stack contains PostgreSQL, MLflow, Fluxnova + an OTel Collector, frontend/UI API,
two evaluation services, and optional Prometheus/Grafana dashboards. Host Python packages run from
one editable `.venv`; infrastructure runs in Podman.

This is the shared setup, demo and troubleshooting guide. Use the
[regression guide](../regression/README.md) for gates, calibration and frozen replay.

- [Platform setup](#platform-setup)
- [Quick start](#quick-start-pods)
- [Demo walkthrough](#demo-walkthrough)
- [Networking](#network-topology-and-windows-fallback)
- [Experiment upgrades and persistence](#mlflow-experiment-initialization-and-persistence)
- [Compose](#alternative-a-single-podman-compose-file)
- [Model providers](#bpmn-agent-llm-provider-openai-default-ollama-alternative)
- [Host debugging](#host-debugging-and-rebuilds)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.11+ (3.11 is the container baseline).
- Podman; on macOS/Windows start a Podman machine. The portability changes were
  developed with Podman 5.8.1 and macOS Bash 3.2. Start with 4 CPUs / 8 GiB VM memory for the OpenAI demo;
  adjust for your machine. Local Ollama needs additional host memory for its models.
- macOS Terminal (zsh is fine: scripts select Bash with their shebang), Windows
  **Git Bash**, or a Linux shell. No GNU Bash upgrade is required on macOS.
- An OpenAI key for the default agent (`gpt-4o`), decision-quality judge
  (`gpt-4.1-mini`) and auxiliary judges (`gpt-4o-mini`).
  Ollama is an optional alternative, described below.
- Copy `.env.example` to `.env` in this directory and set `OPENAI_API_KEY`.
  Keep values shell-compatible; quote values containing spaces or shell characters.
  The scripts source this file; Compose and host tooling read the same settings.

## Platform setup

### macOS

Install Podman and Python 3.11+ (Podman Desktop is optional). With Homebrew:

```bash
brew install podman python@3.11
podman machine list
podman machine start                 # start an existing machine
podman info --format '{{.Host.Arch}}'
```

For a new Apple Silicon VM, AppleHV supports Rosetta for the AMD64 engine image.
Install Rosetta if needed (`softwareupdate --install-rosetta`), then initialize once:

```bash
export CONTAINERS_MACHINE_PROVIDER=applehv
podman machine init --cpus 4 --memory 8192 --disk-size 60
podman machine start
```

Use the selected provider environment in subsequent terminals when managing that VM.
An existing VM can be reused if its x86 execution works. On Intel Macs use the normal
machine defaults. The resource allocation above is a starting point, not a measured minimum.

Verify Apple Silicon emulation before starting Fluxnova:

```bash
podman run --rm --platform linux/amd64 docker.io/library/alpine:3.21 uname -m
podman pull --platform linux/amd64 ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.2.0
```

Expected: `x86_64` and a successful pull. An `exec format error` means the VM's x86
execution/provider configuration needs attention. Other demo images support native ARM64.

### Windows Git Bash

Install Podman (or Podman Desktop), Python 3.11+, and Git Bash. Initialize a machine
once with `podman machine init`, then run `podman machine start`. Use forward-slash
paths and `source .venv/Scripts/activate`. The scripts retain MSYS path handling
and default to the host-network workaround described below.

### Linux and WSL

Install Podman and Python inside the Linux/WSL distro. Rootless Podman runs directly
there: no `podman machine init/start` is needed. Use `.venv/bin/activate` and the
same quick-start commands below. Linux/WSL defaults to bridge networking. If Ollama
runs outside the distro, configure a reachable `OLLAMA_CONTAINER_URL`; Windows and
WSL loopback addresses are not interchangeable.

Apple Silicon startup, artifact proxying, frozen judge calibration and all four live
regression gates have passed local validation with Python 3.11.13, Podman 5.8.1 and
MLflow 3.16.0. Use the same walkthrough when validating other platforms.

## Quick start: pods

From the repository root:

```bash
./setup.sh
source .venv/bin/activate             # macOS/Linux
# source .venv/Scripts/activate       # Windows Git Bash
cp local-dev/.env.example local-dev/.env  # first time only; edit the key next
```

Select a specific interpreter with `PYTHON=python3.11 ./setup.sh` (or its full
path). `fluxnova-run --help`, `eval-service-worker --help`, `eval-trace-listener
--help` and `mlflow-judges --help` verify the editable CLI installation.

After editing `.env`:

```bash
./local-dev/pods-up.sh postgres mlflow fluxnova
./local-dev/pods-up.sh eval-service eval-listener observability

set -a
source local-dev/.env
set +a
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

Bare `./local-dev/pods-up.sh` starts all seven pods in dependency order. Startup waits
for PostgreSQL/MLflow/Fluxnova and the dashboard HTTP endpoints; readiness failures
return non-zero with diagnostics. Worker/listener startup confirms container creation;
their actual scoring is part of the local validation walkthrough.

For an older checkout/store, follow the [experiment upgrade](#upgrade-experiments-created-with-container-local-artifact-paths)
before startup. Keep the `.env.example` image versions, `FLUXNOVA_PLATFORM=linux/amd64`,
`LLM_JUDGE_PROVIDER=openai` and `EVAL_SERVICE_JUDGE_MODEL=openai:/gpt-4.1-mini` for the
default demo. Export `.env` as shown above in every host-tool terminal; `set +a`
stops automatic exporting of new assignments without removing the variables just loaded.

| Service | Host endpoint | Container/pod endpoint (bridge mode) |
| --- | --- | --- |
| PostgreSQL | `localhost:5432` | `postgres-local:5432` |
| MLflow | `http://localhost:5001` | `http://mlflow-local:5000` |
| Fluxnova | `http://localhost:8080/engine-rest` | `http://fluxnova-local:8080/engine-rest` |
| Collector OTLP | `localhost:4317` / `localhost:4318` | `localhost:4317` from Fluxnova |
| Collector metrics | `http://localhost:8889/metrics` | `http://fluxnova-local:8889/metrics` |
| Prometheus | `http://localhost:9090` | `localhost:9090` from Grafana |
| Grafana | `http://localhost:3000` | `observability-local:3000` |
| Demo UI | `http://localhost:8081` | `frontend-local:80` |
| UI API | `http://localhost:8090/health` | `localhost:8090` from nginx |
| Listener control | `http://localhost:8092/config` | `eval-listener-local:8092` |

Fluxnova login is `demo` / `demo`; Grafana allows anonymous viewing and uses
`admin` / `admin` for editing. The provisioned dashboard is **Fluxnova → Fluxnova
GenAI Metrics**. Prometheus/Grafana storage is ephemeral.

## Demo walkthrough

### Frontend and UI API

The default startup includes nginx and the UI API in the shared `frontend-local`
pod/namespace. Open `http://localhost:8081`; nginx proxies `/api/` to the API. The
workflow page starts the current `LoanApprovalProcess_AI` workflow, while the
regression page lists/runs the six golden scenarios and displays per-scorer results.
The auto-eval toggle changes the listener's runtime sample rate. The CLI walkthrough
below separately exercises the smaller loan-assessment and controlled eval workflows.

Bridge-mode UI API calls use internal engine/MLflow/listener DNS names, independently
of host `FLUXNOVA_URL`/port settings. `UI_API_FLUXNOVA_URL`, `UI_API_TRACKING_URI` and
`UI_API_EVAL_LISTENER_URL` override these container endpoints when needed. Host ports
are `FRONTEND_PORT`, `UI_API_PORT` and `EVAL_LISTENER_CONTROL_PORT`; internal bridge
ports stay 80, 8090 and 8092. Recreate affected pods to change settings.

`REBUILD=1 ./local-dev/pods-up.sh frontend` builds changed sources when creating a new
pod; remove the existing frontend pod first with `./local-dev/pods-down.sh frontend`.
Stop/restart the UI API before host-side regression if its workflow mock workers are
already active, so competing worker pools cannot affect validation.

### 1. Check infrastructure and artifact storage

With the quick start complete and `.env` exported:

```bash
podman pod ps
podman ps
curl -fsS "http://localhost:${MLFLOW_PORT:-5001}/version"
curl -fsS "${FLUXNOVA_URL}/engine"
podman exec mlflow python -c "from pathlib import Path; print(Path('/mlflow-runtime/headers.yaml').read_text())"
python local-dev/mlflow/check_artifacts.py
```

Expected: running services, MLflow `3.16.0`, an engine list containing `default`,
and a generated numeric experiment ID (not a fixed value). The artifact smoke
command uploads/downloads a small file and prints a `mlflow-artifacts:/...` URI.
It makes no model calls. The worker/listener containers must remain running;
their first startup builds the images. Logs: `podman logs <container-name>`.

### 2. Run the loan assessment

```bash
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

Expected: deployment, a printed process instance ID, and process completion. Save
the ID. The downstream tools are mocked, but the agent makes real model calls.
Inspect the completed process in Fluxnova Cockpit (`demo` / `demo`).

### 3. Verify traces, assessments and metrics

In MLflow, open the experiment named by `EVAL_SERVICE_EXPERIMENT_NAME` (including
any `-v2` suffix), then **Traces**. After export and listener polling, find the
completed trace with `invoke_agent`, `chat` and `execute_tool` spans. Confirm
`decision_quality`, `evidence_citation` and deterministic assessments appear.

```bash
podman logs --tail 80 eval-trace-listener
curl -fsS "http://localhost:${OTEL_METRICS_PORT:-8889}/metrics" | grep '^gen_ai_'
```

Expected: GenAI samples after a run, the collector target **UP** at Prometheus's
`/targets` page, and token/latency/tool-call data in Grafana's provisioned dashboard.
Allow an export/scrape cycle. If the workflow completes without traces, inspect
collector/engine logs and the generated experiment header; HTTP health alone does
not establish end-to-end telemetry delivery.

### 4. Run the in-process evaluation workflow

In a second terminal, activate `.venv` and export `.env` as in the quick start, then
leave persistent mock workers running:

```bash
fluxnova-run-mock-workers fluxnova-runner/config/loan-assesment-eval.yml
```

In the original terminal:

```bash
fluxnova-run fluxnova-runner/config/loan-assesment-eval.yml
podman logs --tail 80 eval-service-worker
```

The runner returns when the agent Call Activity finishes; trace export and judging
continue asynchronously. In Cockpit, confirm the parent process receives `evalPassed`
and `evalRationale` and advances through the evaluation gateway. A failed evaluation
routes to human review; a pass proceeds through reporting/approval review. Waiting
at a human task is expected. Check that the worker completed the task rather than
creating an incident, and inspect the corresponding MLflow assessments.

The separate mock-worker terminal keeps reporting tools alive after the runner
returns. Stop it with **Ctrl+C** after checking the process and before regression.

#### Controlled human-review routing

To test the failure gateway, stop the eval worker (`podman stop eval-service-worker`)
and any host copy, keep the separate mock workers running, and start a new eval
workflow. Pass the **parent** instance ID printed by the runner to:

```bash
python -m regression.check_review_route <parent-process-instance-id>
podman start eval-service-worker
```

Expected: `UserTask_ReviewFailedEval`. This deliberately sets `evalPassed=false`
to validate BPMN routing; the frozen judge calibration separately checks invalid
model outputs. A worker's lock can remain after shutdown, and an outstanding long
poll may acquire a newly-created task. The helper checks the container is stopped,
reclaims only the selected parent's known eval/validation-worker lock, and includes
the server response body on errors. It refuses unrelated tasks/owners and is
read-only if the process is already at review. Restart the eval worker even if a
check fails, then stop the standalone mock workers before running regression.

### 5. Validate regression and persistence

Follow the [regression validation sequence](../regression/README.md#validation-sequence)
for frozen judge calibration, all four live gates and report replay.

Record a trace ID, then recreate the services:

```bash
./local-dev/pods-down.sh
./local-dev/pods-up.sh
```

Expected: the previous experiment, trace and assessments remain; another workflow
still exports successfully. The experiment ID is reused. Prometheus/Grafana storage
is ephemeral, while the datasource/dashboard are provisioned again. Finish with
`./local-dev/pods-down.sh` and, on macOS/Windows, `podman machine stop` if desired.
Normal teardown preserves data; `--delete-data` deliberately resets databases/artifacts.

## Network topology and Windows fallback

macOS/Linux pod scripts default to **bridge networking**. Each pod joins
`fluxnova-dev`; internal requests use pod DNS names and fixed container ports.
Published ports provide access from the physical host, including through the Mac VM.
Fluxnova and the collector share a pod namespace, as do Prometheus and Grafana.

Windows Git Bash defaults to the existing **host-network workaround** for reported
OTLP export/scrape problems in isolated namespaces. Select a mode explicitly in `.env`:

```dotenv
DEV_NETWORK_MODE=bridge
# DEV_NETWORK_MODE=host
```

In host mode Fluxnova, the collector, the eval worker and observability use the
**Linux VM's** host network. PostgreSQL and MLflow keep published bridge ports.
The worker reaches Fluxnova and MLflow at VM-local published ports; Prometheus
scrapes `localhost:8889` using `prometheus-host.yml`. On macOS, VM host-network
services are not guaranteed to be accessible at Mac `localhost`; use bridge mode.
The Windows WSL IP fallback remains available when localhost forwarding fails.

Changing modes requires removing/recreating pods with `pods-down.sh` / `pods-up.sh`.
The older OTLP issue has not been reproduced as part of these changes; validate
trace arrival as well as HTTP reachability. If reporting a failure, include the
Podman version, VM provider, mode, engine logs, and collector logs.

`host.containers.internal` is reserved for reaching services on the **physical host**
(such as native Ollama), not for service-to-service routing. We use Podman's own
host-name resolution rather than overriding it with `--add-host ...:host-gateway`.

## Apple Silicon and Fluxnova image

The public engine image is
`ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.2.0`. Its manifest is **AMD64-only**,
so the scripts and Compose explicitly set `FLUXNOVA_PLATFORM=linux/amd64` for
Fluxnova. An Apple Silicon Podman machine must support x86 execution (for example
AppleHV + Rosetta). See [macOS setup](#macos) for the emulation smoke command.

The pinned PostgreSQL, MLflow, collector, Prometheus, Grafana and Python base images
have both Linux ARM64 and AMD64 manifests; evaluation images build for the VM's
native architecture. They do not need to run under emulation.

The engine is built in the separate `fluxnova-bpm-platform` source repository.
When a native ARM64/multi-architecture engine image is published, set both
`FLUXNOVA_IMAGE` and `FLUXNOVA_PLATFORM=linux/arm64` on Apple Silicon. Publishing that
external image is a follow-up; this repository provides the emulated-image path.

## MLflow experiment initialization and persistence

Both orchestration methods use `mlflow/start.sh` to install the PostgreSQL driver,
run `mlflow db upgrade`, and start MLflow **3.16.0**, matching Python clients.
`mlflow/bootstrap.py` creates or resolves `EVAL_SERVICE_EXPERIMENT_NAME`, then
atomically writes its real numeric ID to `/mlflow-runtime/headers.yaml`.
The collector reads that header map from the shared `mlflow-local-runtime` volume.
MLflow health only passes once the header file and HTTP endpoint are ready.

No fixed ID, pre-existing experiment, or manual database edit is required.
`MLFLOW_EXPERIMENT_ID` in an older `.env` is obsolete and ignored. All agent traces
go to the configured experiment regardless of BPMN process key; both evaluation
services read that same experiment. Regression evaluation runs share the trace
experiment by default; `MLFLOW_EXPERIMENT_NAME` can select a separate regression
experiment. Raw regression traces are tagged `source=regression` for listener exclusion.

PostgreSQL uses the named volume `postgres-local-data` (host bind mounts are
unsuitable for PGDATA ownership through VM file sharing). Its initialization
script creates the `mlflow` and `fluxnova` roles/databases. Credentials in `.env`
are applied on the first startup of an empty volume; later password changes require
SQL role updates or deliberate data reinitialization.
MLflow artifacts use the host bind mount `local-dev/.mlflow/artifacts`.
The server advertises `mlflow-artifacts:/` URIs and proxies uploads/downloads over
HTTP; `/mlflow-artifacts` is the server's storage destination, never a host client path.

### Upgrade experiments created with container-local artifact paths

Server flags do not rewrite old experiment/run artifact locations. Preserve the old
experiments and set fresh names in your existing `.env`, for example:

```dotenv
EVAL_SERVICE_EXPERIMENT_NAME=fluxnova-loanAssessmentEvalProcess-v2
MLFLOW_EXPERIMENT_NAME=fluxnova-loanAssessmentProcess-regression-v2
```

Recreate the stack with `pods-down.sh` / `pods-up.sh` (without `--delete-data`), then
reload `.env` in host terminals. Startup refuses to reuse a container-local trace
experiment; regression similarly rejects local artifact paths with upgrade guidance.
Restarting the Podman VM or an existing pod does **not** replace container environment
variables. Even when `.env` already says `-v2`, an old MLflow container may still
select the legacy experiment. The up script detects that mismatch before restarting
it and provides a pod-recreation command. If a process exits during readiness or
experiment initialization, startup fails immediately with its exit status and recent
logs instead of repeatedly executing probes against a stopped container.
Validate the host proxy before running model-driven tests:

```bash
python local-dev/mlflow/check_artifacts.py
```

The isolated integration test needs no Podman, credentials or model calls:
`RUN_MLFLOW_PROXY_TEST=1 python -m pytest local-dev/tests/test_artifact_proxy.py -q`.

```bash
./local-dev/pods-down.sh                  # removes pods, preserves DB/artifacts
./local-dev/pods-up.sh                    # recreates with current configuration
./local-dev/pods-down.sh --delete-data    # deliberately wipes DB and artifacts
```

Pod scripts are idempotent: existing pods are started, not recreated. Recreate
them after changing image tags, `.env`, model settings or topology. The runtime
volume contains generated headers only; MLflow rewrites them on every server start.

### Pull/startup failure recovery

Before creating a pod, scripts pull all required images (or build the eval image).
Cached images are reused, including a platform check for Fluxnova, and container
starts use `--pull=never`. Interrupted pull CLI calls are retried up to three times;
`IMAGE_PULL_ATTEMPTS` and `IMAGE_PULL_RETRY_DELAY` (seconds) override this behavior.
Registry-level retries are also enabled, but the whole-command retry is needed for
remote-client `unexpected EOF` failures. Python base images are pulled before builds.

If a container fails to start, only the new pod created by that script is cleaned
up; volumes and artifacts remain. Existing incomplete pods get a recovery command.
Port-binding errors report the applicable configuration, and an existing MLflow
pod with a different published port must be recreated before it is started.
Once containers are successfully created, readiness failures keep them for log
inspection. The [troubleshooting section](#troubleshooting)
includes a direct-VM pull workaround using the active rootful/rootless store.
These helpers apply to the pod scripts; Compose uses its provider's pull/start behavior.

## Alternative: a single Podman Compose file

Requires a compose provider (`podman-compose` or Docker Compose), in addition to
Podman. Compose always uses the portable **bridge** topology; `DEV_NETWORK_MODE`
applies only to the pod scripts. Choose one orchestration method per session;
both use the same container names, network and data volumes.

```bash
cd local-dev
podman compose up -d
podman compose --profile eval --profile grafana up -d --build
podman compose ps
podman compose logs -f fluxnova-local
podman compose --profile eval --profile grafana down
```

Services are named `<container>-local`. The collector's network namespace has the
`fluxnova-local` DNS alias and publishes Fluxnova's port; the engine shares that
namespace. MLflow's healthcheck gates collector startup, and the eval worker waits
for Compose's explicit engine REST healthcheck (the image has none). `down -v` also deletes named volumes but leaves
the host artifact directory intact; pod scripts' `--delete-data` clears artifacts too.

## BPMN agent LLM provider (OpenAI default, Ollama alternative)

Default demo setup uses OpenAI for both the agent and evaluation services. The
worker is configured by `.env` to call `openai:/gpt-4.1-mini` directly, so no MLflow
AI Gateway endpoint or local model download is needed. The worker package's
standalone default remains `gateway:/fluxnova-judge-oai` for existing gateway users;
the local startup scripts pass the configured model explicitly.

Decision-quality judging defaults to `gpt-4.1-mini` after repeated calibration
found false negatives with `gpt-4o-mini` on valid evidence-backed responses.
`DECISION_QUALITY_MODEL` can override the host/listener semantic judge using a full
MLflow model URI; an explicit `EVAL_SERVICE_JUDGE_MODEL` wins for the worker.
Recreate/rebuild the evaluation pods after changing these settings. Golden matching
and evidence-citation scoring use `gpt-4o-mini` independently.

For native Ollama on a Mac:

1. Install [Ollama](https://ollama.com/download/mac). Run it natively to use Apple GPU
   acceleration. Pull `gemma4:e2b` (or adapt the agent/judge configuration to another
   appropriate model). Check `ollama show gemma4:e2b` for tool-calling support.
2. Quit Ollama, run `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"`, and reopen the app.
   Alternatively, run `OLLAMA_HOST=0.0.0.0:11434 ollama serve` in a terminal after
   stopping the app. [Official environment instructions](https://docs.ollama.com/faq#setting-environment-variables-on-mac).
3. Set these `.env` values (base URLs have **no `/v1` suffix** for these direct clients):
   ```dotenv
   LLM_JUDGE_PROVIDER=ollama
   EVAL_SERVICE_JUDGE_MODEL=ollama:/gemma4:e2b
   OLLAMA_API_BASE=http://localhost:11434
   OLLAMA_CONTAINER_URL=http://host.containers.internal:11434
   ```
4. To use Ollama for the BPMN agent as well, change `default.yml`'s
   `spring.ai.model.chat` to `ollama`, and the `agent:config` in
   `bpmn/loan-assesment.bpmn` to `provider="ollama" model="gemma4:e2b"`. Both settings
   must agree. The startup scripts pass the container base URL to Spring.
5. Recreate affected pods/containers. Export the updated `.env` before running host
   tools. The regression suite serializes judge calls when Ollama is selected.
6. Validate container access, using the Python already present in the listener:
   ```bash
   podman exec eval-trace-listener python -c "import os, urllib.request; print(urllib.request.urlopen(os.environ['OLLAMA_API_BASE'] + '/api/version').read().decode())"
   ```

On Windows, set `OLLAMA_HOST` in the user environment and restart Ollama; verify
container connectivity before running evaluations. Some WSL setups need a host
gateway address in `OLLAMA_CONTAINER_URL`. Host/VM `localhost` are distinct.

When switching an already-deployed BPMN between providers, the engine may reject
the old deployment during cleanup. Delete that deployment while the **old** provider
is active, then switch the engine/provider and redeploy.

### MLflow AI Gateway endpoint for automatic evaluation judges

Automatic sampling through `mlflow-judges` still requires a gateway endpoint.
In MLflow's **AI Gateway**, create `fluxnova-judge` with your chosen provider/model.
For host Ollama the gateway connection base URL is
`http://host.containers.internal:11434/v1` (**including `/v1` for the gateway**),
and a placeholder API key is sufficient. MLflow's container must reach that URL.
To use this endpoint for the worker, set
`EVAL_SERVICE_JUDGE_MODEL=gateway:/fluxnova-judge` and recreate its container.

```bash
mlflow-judges --experiment fluxnova-loanAssessmentEvalProcess start --sample-rate 0.1
mlflow-judges --experiment fluxnova-loanAssessmentEvalProcess status
mlflow-judges --experiment fluxnova-loanAssessmentEvalProcess stop
```

Use an HTTP `--tracking-uri`, not a direct PostgreSQL URI. This gateway setup is
optional for the default demo's direct worker/listener/regression judges.

## Host debugging and rebuilds

`./setup.sh` installs all five packages editable (including UI API and regression
JSON-report dependencies). To debug Python services against
container infrastructure, stop the corresponding service pods first:

```bash
./local-dev/pods-down.sh eval-service eval-listener
source .venv/bin/activate
set -a
source local-dev/.env
set +a
eval-service-worker --fluxnova-url "$FLUXNOVA_URL" --tracking-uri "http://localhost:${MLFLOW_PORT:-5001}"
# In another terminal with the same activation/environment:
eval-trace-listener --tracking-uri "http://localhost:${MLFLOW_PORT:-5001}"
```

In PyCharm/IntelliJ's Python plugin select `.venv/bin/python` (Mac) or
`.venv/Scripts/python.exe` (Windows) as the **project interpreter**. Shared `.run/`
configurations use that interpreter and `local-dev/.env`; adjust their host URL
arguments if overriding ports. Stop service containers before debugging host copies.
Editable host changes take effect on the next process start.

Containers contain source snapshots. To rebuild after Python changes:

```bash
./local-dev/pods-down.sh eval-service eval-listener
REBUILD=1 ./local-dev/pods-up.sh eval-service eval-listener
# Compose alternative, from local-dev/: podman compose --profile eval up -d --build
```

## Port overrides and checks

MLflow defaults to host port **5001** to avoid macOS AirPlay Receiver on `5000`.
Override `MLFLOW_PORT` if another app occupies `5001`. Internal bridge URLs still
use `5000`; host tools use the published port. The
regression suite reads `MLFLOW_PORT` from `.env`. Set `FLUXNOVA_PORT` similarly;
exported `FLUXNOVA_URL` in the template expands that port and overrides runner YAML.
Host debugging services need explicit tracking/engine URL flags for custom ports.
Other published ports: `POSTGRES_PORT`, `OTEL_GRPC_PORT`, `OTEL_HTTP_PORT`,
`OTEL_METRICS_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`. Recreate affected pods.
Host-network collector ports remain `4317`, `4318`, `8889`.

Run unit suites separately (some suites use same-named helper/test modules):

```bash
python -m pytest fluxnova-runner/tests -q
python -m pytest fluxnova-mlflow-dataset/tests -q
python -m pytest eval-service-worker/tests -q
python -m pytest eval-trace-listener/tests -q
python -m pytest local-dev/tests -q
python -m pytest ui-api/tests -q
```

Frontend checks: run `npm ci`, `npm run build` and `npm run lint` from `frontend/`.

The startup tests use a fake Podman and test bootstrap responses; they do not start
a VM or replace end-to-end validation. Follow the demo walkthrough to check actual
trace delivery, scoring, regression gates and restart persistence.

## Troubleshooting

### Image pull fails with unexpected EOF

`failed to decode message from stream: unexpected EOF` is a Podman remote pull
failure before the application starts. The scripts retry complete pull commands
before creating pods. If it persists, bypass that API by pulling inside the VM.
Use `podman machine list` for its name and
`podman info --format '{{.Host.Security.Rootless}}'` for the active storage mode.
Run the appropriate command (replace the default machine name if needed):

```bash
# Rootless=false: rootful store
podman machine ssh podman-machine-default sudo podman --remote=false pull ghcr.io/mlflow/mlflow:v3.16.0
# Rootless=true: rootless store
podman machine ssh podman-machine-default podman --remote=false pull ghcr.io/mlflow/mlflow:v3.16.0
```

Match the client's machine and storage mode, confirm `podman image inspect
ghcr.io/mlflow/mlflow:v3.16.0` succeeds from the host, then retry startup. A partial
pod left by older scripts can be recreated with `podman pod rm --force mlflow-local`
followed by `./local-dev/pods-up.sh postgres mlflow fluxnova`. This preserves volumes
and artifact files. If Podman disconnects, check `podman machine list` before restarting it.

### Port already in use

MLflow's host default is `5001`; containers still use `5000`. For a conflict, choose
a free `MLFLOW_PORT` in `.env`. On a Mac, `lsof -nP -iTCP:5001 -sTCP:LISTEN` identifies
the listener. Port `5000` is commonly occupied by AirPlay Receiver. Recreate the
MLflow pod after editing the port; restart alone cannot change published mappings.

### MLflow exits or reports container state improper

Run `podman logs --tail 80 mlflow`. If bootstrap names a container-local artifact
experiment, follow the [experiment upgrade](#upgrade-experiments-created-with-container-local-artifact-paths).
An old container can retain the legacy name even after `.env` is corrected. The
scripts detect that drift and show a recreation command. They also stop immediately
with exit status and logs if a container exits during readiness, rather than repeating
`podman exec` against a stopped container. Recreate evaluation pods after experiment
changes too; use the rebuild commands above to pick up changed Python scorers.
