# Local development with Podman: macOS, Windows and Linux

The stack contains PostgreSQL, MLflow, Fluxnova + an OTel Collector, two evaluation
services, and optional Prometheus/Grafana dashboards. Host Python packages run from
one editable `.venv`; infrastructure runs in Podman.

**For a complete Mac walkthrough, including expected validation results, see
[RUNNING-MACOS.md](../RUNNING-MACOS.md).** Work is tracked in
[issue #21](https://github.com/ScottLogic/fluxnova-eval-demo/issues/21).

## Prerequisites

- Python 3.11+ (3.11 is the container baseline).
- Podman; on macOS/Windows start a Podman machine. The portability changes were
  developed with Podman 5.8.1 and macOS Bash 3.2; full-stack platform validation is
  described in the Mac guide. Start with 4 CPUs / 8 GiB VM memory for the OpenAI demo;
  adjust for your machine. Local Ollama needs additional host memory for its models.
- macOS Terminal (zsh is fine: scripts select Bash with their shebang), Windows
  **Git Bash**, or a Linux shell. No GNU Bash upgrade is required on macOS.
- An OpenAI key for the default agent (`gpt-4o`) and judges (`gpt-4o-mini`).
  Ollama is an optional alternative, described below.
- Copy `.env.example` to `.env` in this directory and set `OPENAI_API_KEY`.
  Keep values shell-compatible; quote values containing spaces or shell characters.
  The scripts source this file; Compose and host tooling read the same settings.

## Quick start: pods

From the repository root:

```bash
./setup.sh
source .venv/bin/activate             # macOS/Linux
# source .venv/Scripts/activate       # Windows Git Bash
cp local-dev/.env.example local-dev/.env  # first time only; edit the key next
```

After editing `.env`:

```bash
./local-dev/pods-up.sh postgres mlflow fluxnova
./local-dev/pods-up.sh eval-service eval-listener observability

set -a
source local-dev/.env
set +a
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
```

Bare `./local-dev/pods-up.sh` starts all six pods in dependency order. Startup waits
for PostgreSQL/MLflow/Fluxnova and the dashboard HTTP endpoints; readiness failures
return non-zero with diagnostics. Worker/listener startup confirms container creation;
their actual scoring is part of the local validation walkthrough.

| Service | Host endpoint | Container/pod endpoint (bridge mode) |
| --- | --- | --- |
| PostgreSQL | `localhost:5432` | `postgres-local:5432` |
| MLflow | `http://localhost:5001` | `http://mlflow-local:5000` |
| Fluxnova | `http://localhost:8080/engine-rest` | `http://fluxnova-local:8080/engine-rest` |
| Collector OTLP | `localhost:4317` / `localhost:4318` | `localhost:4317` from Fluxnova |
| Collector metrics | `http://localhost:8889/metrics` | `http://fluxnova-local:8889/metrics` |
| Prometheus | `http://localhost:9090` | `localhost:9090` from Grafana |
| Grafana | `http://localhost:3000` | `observability-local:3000` |

Fluxnova login is `demo` / `demo`; Grafana allows anonymous viewing and uses
`admin` / `admin` for editing. The provisioned dashboard is **Fluxnova → Fluxnova
GenAI Metrics**. Prometheus/Grafana storage is ephemeral.

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
AppleHV + Rosetta). See the Mac guide for a smoke command before starting the stack.

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
services read that same experiment. Regression results use a separate
`fluxnova-loanAssessmentProcess-regression` experiment.

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
inspection. The [Mac troubleshooting guide](../RUNNING-MACOS.md#troubleshooting)
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
for the engine's image healthcheck. `down -v` also deletes named volumes but leaves
the host artifact directory intact; pod scripts' `--delete-data` clears artifacts too.

## BPMN agent LLM provider (OpenAI default, Ollama alternative)

Default demo setup uses OpenAI for both the agent and evaluation services. The
worker is configured by `.env` to call `openai:/gpt-4o-mini` directly, so no MLflow
AI Gateway endpoint or local model download is needed. The worker package's
standalone default remains `gateway:/fluxnova-judge` for existing gateway users;
the local startup scripts pass the configured model explicitly.

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

`./setup.sh` installs all four packages editable. To debug Python services against
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
```

The startup tests use a fake Podman and test bootstrap responses; they do not start
a VM or replace end-to-end validation. Follow the Mac walkthrough to check actual
trace delivery, scoring, regression gates and restart persistence.
