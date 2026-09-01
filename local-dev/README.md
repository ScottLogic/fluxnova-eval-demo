# Local development: Fluxnova + OTel Collector + MLflow (Podman)

This directory contains everything needed to run the **Fluxnova engine**, the **OTel Collector**, and (optionally)
the **MLflow tracking server** as containers for local development, using [Podman](https://podman.io) — grouped into
a single Podman pod per service (`fluxnova-up.sh` / `fluxnova-down.sh` for Fluxnova + the OTel Collector, and
`mlflow-up.sh` / `mlflow-down.sh` for MLflow), with no compose provider required.

## Prerequisites

- **[Podman](https://podman.io/docs/installation)** installed, with a running machine/VM on Windows and macOS
  (`podman machine init && podman machine start`) — not needed on Linux. [Podman Desktop](https://podman-desktop.io)
  is recommended, though not required, for a GUI to view/manage pods, containers, and logs.
- **The Fluxnova image**, pulled from GitHub Container Registry — see "Fluxnova image" below. `podman run` (used by
  `fluxnova-up.sh`) pulls it automatically the first time if it isn't already present locally.
- **The MLflow tracking server running** (either on the host — see the main README's "Running the MLflow tracking
  server" — or as the `mlflow-local` pod below) — the OTel Collector sends traces to it via `host.containers.internal`.

## Starting Fluxnova + the OTel Collector

`fluxnova-up.sh` starts both containers grouped in a single **Podman pod**. Run it from **Git Bash** on Windows (see
the main README's "A note on shells (Windows)").

```bash
cd local-dev
# adjust .env if needed — FLUXNOVA_IMAGE defaults to the public GHCR image (see "Fluxnova image" below)

./fluxnova-up.sh      # start the pod
./fluxnova-down.sh    # stop and remove it
```

This creates a `fluxnova-local` pod publishing ports `8080` (Fluxnova), `4317`/`4318` (OTel Collector gRPC/HTTP).
Both containers share one network namespace, so they reach each other via `localhost` rather than by container name
— that's why `default.yml` (mounted by the pod script) points `exporterEndpoint` at `http://localhost:4317`.

- **`fluxnova`** — the Fluxnova engine, published on `http://localhost:8080` (matching `fluxnova_url` in the harness
  config files), with `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at the collector container.
- **`otel-collector`** — an `otlp` receiver (gRPC `4317` / HTTP `4318`, also published to the host) piped through an
  `otlphttp` exporter to the MLflow tracking server (`http://host.containers.internal:5000` or the shared
  `fluxnova-dev` network's `mlflow-local` pod, auto-suffixed with `/v1/traces`). Make sure the MLflow tracking server
  is already running before starting the pod.

See `default.yml` and `otel-collector-config.yaml` for details and adjust image names, ports, or the collector
pipeline as your actual Fluxnova image requires.

### Fluxnova image

`FLUXNOVA_IMAGE` in `.env` points at a versioned image on GitHub Container Registry (GHCR):
`ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<tag>`. The package is **public**, so `podman run` (via
`fluxnova-up.sh`) pulls it automatically on first use with no login required — you don't need to build it yourself
for normal local dev.

**Publishing a new version:** the Fluxnova image is built from the separate `fluxnova-bpm-platform` source (not this
repo). After building it locally there (`podman build -t fluxnova-edd-platform:<new-tag> .`), tag and push it to GHCR:

```bash
podman login ghcr.io -u <github-username>   # needs classic PAT with write:packages (+ repo if private)
podman tag fluxnova-edd-platform:<new-tag> ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<new-tag>
podman push ghcr.io/dogle-scottlogic/fluxnova-edd-platform:<new-tag>
```

Then bump `FLUXNOVA_IMAGE` in `.env` (and this README's example tag above, if it's a new default) to the new tag so
everyone picks it up.

Once Fluxnova responds, `fluxnova-up.sh` opens the Fluxnova web UI (`/fluxnova-welcome/index.html`) in your default
browser automatically — same behaviour as `mlflow-up.sh` below, including the `localhost`-unreachable fallback
(see "Troubleshooting"). Set `FLUXNOVA_OPEN_BROWSER=false` to skip the auto-open.

## Optional: run the MLflow tracking server in its own Podman pod

`mlflow-up.sh` / `mlflow-down.sh` run the MLflow tracking server (see the main README's "Running the MLflow
tracking server") as a container instead of a host process, as its own single-container `mlflow-local` pod — kept
separate from `fluxnova-local` since it's a longer-lived dev service you likely want to start/stop independently of
any one Fluxnova run. Run from **Git Bash**:

```bash
cd local-dev
# adjust .env if you haven't already; set MLFLOW_IMAGE/MLFLOW_PORT/MLFLOW_BACKEND_STORE_DIR if needed

./mlflow-up.sh      # start it
./mlflow-down.sh    # stop and remove it (the SQLite backend store on disk is untouched)
```

This uses the official `ghcr.io/mlflow/mlflow` image, bind-mounting `harness/.mlflow` (the same path already used by
`mlflow-eval` and the host-run `mlflow server`/`mlflow ui` commands) so they all read/write the same `mlflow.db` — you
can freely switch between running MLflow as a host process and as this container. The OTel Collector's `otlphttp`
exporter (`http://host.containers.internal:5000`) reaches it exactly as it would a host-run server, since the pod's
port is published to the host either way.

Once the container is up, `mlflow-up.sh` waits for it to respond, then opens the UI in your default browser
automatically (see "Troubleshooting" below for what it does if `localhost` isn't reachable). Set
`MLFLOW_OPEN_BROWSER=false` to skip the auto-open.

### Troubleshooting: `localhost:5000` unreachable from Windows, but the container is running

On some Windows/WSL2 setups, MLflow's Python server is unreachable via `localhost`/`127.0.0.1` from *outside* WSL —
`podman ps` shows it running, and it responds fine to requests made *inside* the Podman machine, but everything
through the WSL2 `localhost`-forwarding relay silently resets (`curl` reports "Empty reply from server"). This
reproduced consistently in testing even across a full `wsl --shutdown` + restart, while other containers (e.g.
`nginx`, the Fluxnova/Java container above) were unaffected on the same machine — so it appears specific to this
Python server plus this Windows/WSL2 networking configuration, not a bug in the pod script or the MLflow image
itself.

`mlflow-up.sh` handles this automatically: if `http://localhost:$MLFLOW_PORT` doesn't respond within a few
seconds, it looks up the Podman machine's own IP (`wsl -d podman-machine-default -- ip -4 addr show eth0`), checks
that it's reachable, and uses it instead — both for the printed URLs and for the browser it opens. If you're doing
this manually (e.g. pointing the OTel Collector's `otlphttp` exporter somewhere), the same commands are:

```bash
wsl -d podman-machine-default -- ip -4 addr show eth0   # note the inet address, e.g. 172.28.x.x
curl http://<that-ip>:5000/version                       # works even when localhost:5000 doesn't
```

That IP can change on VM restart, so re-run `mlflow-up.sh` (or the `wsl` command above) if it stops working. If
you don't hit this on your machine, `http://localhost:5000` works as documented above.

## MLflow AI Gateway endpoint for automatic evaluation judges

MLflow's built-in AI Gateway (`http://localhost:5000/#/gateway`, part of the same `mlflow-local` pod/server — no
separate service to run) is required for **automatic evaluation** judges (`Scorer.register()` + `Scorer.start()`),
which — unlike offline/EDD judges — must reference a `gateway:/<endpoint-name>` model URI rather than calling Ollama
directly. Here's how to reproduce a working local `fluxnova-judge` endpoint backed by Ollama:

1. Make sure `mlflow-local` is running (`./mlflow-up.sh`) with the `--add-host host.containers.internal:host-gateway`
   flag included at pod-create time (already the default in this script) — without it, the container can't reach a
   host-run Ollama server at all.
2. Open `http://localhost:5000/#/gateway` and click **Create Endpoint**.
3. Name it `fluxnova-judge`, select provider **Ollama**.
4. Pick a model from the picker — at time of writing only `llama3.1` was offered here even though `llama3.2` was
   already pulled locally (`ollama list`); `llama3.1` works fine and is what this repo's example endpoint uses. Note
   this means the automatic-evaluation judge model may differ from whatever `ollama/llama3.2` model the existing
   hand-rolled `_llm_judge()` offline scorers use, unless reconciled later.
5. Create a new connection for it:
   - **Base URL**: `http://host.containers.internal:11434/v1` — the `/v1` suffix is required. MLflow's
     `OllamaProvider` appends `/chat/completions` directly onto whatever base URL is configured, with no separate
     `/v1` insertion, so omitting it causes every request to 404 (you'll see Ollama's own literal
     `{"detail":{"message":"404 page not found"}}` body passed through — this looks like an MLflow failure at first
     glance but is actually Ollama's router rejecting the wrong path).
   - **API key name/value**: any placeholder (e.g. `OLLAMA_API_KEY` / `unused`) — local Ollama needs no real
     authentication, but the UI form requires something be entered.
6. Save. There's no in-place "edit the base URL" option once an endpoint/connection is created in this MLflow
   version — to fix a mistake, delete and recreate rather than editing.
7. Verify with the OpenAI-compatible unified endpoint (works with `curl` or the OpenAI Python SDK):
   ```python
   from openai import OpenAI

   client = OpenAI(
       base_url="http://localhost:5000/gateway/mlflow/v1",
       api_key="unused",  # not validated for a local Ollama-backed endpoint
   )
   response = client.chat.completions.create(
       model="fluxnova-judge",  # the endpoint name, not the underlying Ollama model name
       messages=[{"role": "user", "content": "How are you?"}],
   )
   print(response.choices[0].message)
   ```
   A real completion coming back (rather than a 404/500) confirms the endpoint is wired up correctly.

## Toggling automatic evaluation judges on/off

Once the `fluxnova-judge` gateway endpoint exists (see above), use the `mlflow-judges` CLI (installed alongside
`mlflow-eval` — run `pip install -e .` in `harness/` after pulling if it's missing) to register and toggle automatic
judges for a given experiment. It targets every judge returned by `mlflow_eval.main.automatic_judges()` (currently
`decision_quality`):

```bash
# Register + start automatic sampling (registers on first run automatically)
mlflow-judges --experiment fluxnova-loanAssessmentProcess start --sample-rate 0.1

# Stop sampling (judge stays registered; cheap to restart later)
mlflow-judges --experiment fluxnova-loanAssessmentProcess stop

# Show current registration/sampling state
mlflow-judges --experiment fluxnova-loanAssessmentProcess status
```

`--tracking-uri` defaults to `http://localhost:5000` (the running `mlflow-local` server) — this **must** be an
HTTP(S) address, not a direct `sqlite:///...` path, because gateway-backed judges route through the server process
itself. Add `--filter-string` to `start` to restrict which traces get scored (e.g. to exclude EDD regression runs).

## Targeting a different MLflow experiment

By default, workflow runs/records use a single experiment named `fluxnova-<process_key>` (e.g.
`fluxnova-loanAssessmentProcess`) — no dev/prod split (a `dev`/`prod` environment-suffix scheme was tried and then
reverted; not needed for this demo's scope). To point at a different experiment without changing any code, set an
explicit override in the workflow config:

```yaml
mlflow_dataset:
  enabled: true
  experiment_name: fluxnova-loanAssessmentProcess-demo   # any name you like
```

If omitted, it defaults to `fluxnova-<process_key>` as before — existing configs don't need any changes.

If you need to rename an existing experiment/dataset in place (e.g. after changing this override), use:

```python
import mlflow

mlflow.set_tracking_uri("sqlite:///harness/.mlflow/mlflow.db")
client = mlflow.MlflowClient()
client.rename_experiment("<experiment_id>", "<new-name>")
```

`mlflow.genai.datasets.EvaluationDataset` has no public rename API — if needed, update the `name` column directly in
the `evaluation_datasets` table of the SQLite tracking store instead (safe for local dev data; the `dataset_id`,
schema, and records are untouched, only the lookup name changes).

## eval-service-worker: scoring completed subprocess runs

`eval-service-worker` (see `eval-service-worker/` and `EVAL-SERVICE-WORKER-PLAN.md` at the repo root) is a standalone
BPMN external-task worker that scores a just-completed agentic subprocess run against the `decision_quality` MLflow
judge plus a set of trace-only deterministic scorers (`required_tools_called`, `no_tool_errors`,
`definitive_decision_stated`), reading data purely from MLflow's trace store (no BPMN parsing, no Fluxnova REST
history calls). All scorers' `Feedback` are logged back onto the trace as MLflow assessments grouped under one
Evaluation Run, plus a lightweight MLflow evaluation-dataset record; the task then completes with
`evalPassed`/`evalRationale` output variables — `evalPassed` is driven solely by `decision_quality` (the deterministic
scorers are recorded for visibility/audit only, not yet wired into the gate).

**BPMN wiring:** `bpmn/loan-assesment-eval.bpmn` (a separate process definition, `loanAssessmentEvalProcess`, from the
original `loan-assesment.bpmn`) has a `ServiceTask_EvaluateAgentOutput` on this worker's topic (`agent-output-eval`)
right after the loan-assessment ad-hoc subprocess, followed by `ExclusiveGateway_EvalPassed` routing to
`EndEvent_EvalPassed`/`EndEvent_EvalFailed` based on `evalPassed` — confirmed working end-to-end against a live
process instance. Use `harness/config/loan-assesment-eval.yml` (not `loan-assesment.yml`) to run this BPMN, and set
`MLFLOW_EXPERIMENT_ID` in `.env` to that config's experiment (`fluxnova-loanAssessmentEvalProcess`) so traces route to
where the worker looks for them. You can also trigger a one-off scoring run manually — see
`eval-service-worker/README.md` (or call `eval_service_worker.scoring.score_process_instance(...)` directly) with a
real `processInstanceId` from a completed run.

```bash
cd local-dev
./eval-service-up.sh      # builds the image, starts the eval-service-local pod
./eval-service-down.sh    # stop and remove it
```

This builds `eval-service-worker/Dockerfile` from the repo root (so it can install the local
`fluxnova-mlflow-dataset` path dependency too) and passes `EVAL_SERVICE_FLUXNOVA_URL`/`EVAL_SERVICE_TRACKING_URI`
env vars pointed at the sibling `fluxnova-local`/`mlflow-local` pod names (rather than `localhost`, which only
resolves for host-run tools) on the shared `fluxnova-dev` network. Both those pods must already be running.

The worker has **no config file of its own** — every setting (`fluxnova_url`, `experiment_name`, `process_key`,
`topic`, `judge_model`, `lock_duration_ms`, `tracking_uri`) is a hardcoded default in
`eval-service-worker/src/eval_service_worker/config.py`, overridable via either a CLI flag (e.g. `--tracking-uri`)
or an `EVAL_SERVICE_<NAME>` environment variable (e.g. `EVAL_SERVICE_TRACKING_URI`) — see that file or
`eval-service-worker/README.md` for the full list. This is deliberate: it keeps the worker independently deployable
without depending on `harness`'s workflow YAML.

## Files

| File | Purpose |
|------|---------|
| `fluxnova-up.sh` / `fluxnova-down.sh` | Start/stop the `fluxnova-local` pod (Fluxnova + OTel Collector) |
| `mlflow-up.sh` / `mlflow-down.sh` | Start/stop the `mlflow-local` pod |
| `eval-service-up.sh` / `eval-service-down.sh` | Build/start/stop the `eval-service-local` pod (see above) |
| `default.yml` | Fluxnova config mounted by `fluxnova-up.sh` (OTel plugin → `localhost:4317`, shared pod network namespace) |
| `otel-collector-config.yaml` | OTel Collector pipeline: `otlp` receiver → `otlp_http` exporter to MLflow |
| `.env` | Environment values (image names/ports/paths) — adjust as needed |

