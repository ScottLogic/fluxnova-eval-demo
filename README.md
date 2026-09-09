# Fluxnova Eval Demo

A set of tooling, test harness and evaluation framework for Fluxnova workflows that include AI-driven agentic
subprocesses.

Goals of this project are:

- Create an Eval Test framework which facilitates Evaluation Driven Design (EDD). This will allow a demo of how you can
  build out an agentic workflow using EDD.
- Add an OTel collector and gen_ai* metrics and tracing with a suitable dashboard. This will allow a demo of real time
  production monitoring.
- Add an Eval task to production level process runs which will facilitate checks on responses and break-glass to a human
  in Production environments.

## Overview

This project is split into three independent Python packages:

1. **`fluxnova-runner`** ([`fluxnova-runner/`](fluxnova-runner/README.md)) — deploys a BPMN workflow to Fluxnova,
   starts a process instance with configurable input variables, drives mock external-task workers, and polls until
   the sub-process completes.
2. **`fluxnova-mlflow-dataset`** ([`fluxnova-mlflow-dataset/`](fluxnova-mlflow-dataset/README.md)) — a small shared
   library (no CLI) used by the harness's `mlflow-eval` suite. It provides:
    - **collection** (`collect_new_runs`) — an on-demand pre-step (run via `mlflow-eval --collect`, not a background
      service) that finds newly-completed agentic subprocess runs directly in MLflow's own trace store (populated by an
      OTel Collector exporting straight to MLflow), builds an agent-history report by joining that trace data with the
      static BPMN definition and the run's final process variables (read from Fluxnova's core REST API), and upserts it
      into a persistent MLflow evaluation dataset (skip-if-exists/idempotent).
    - **record shaping/read/write** — builds MLflow-dataset records from agent-history data and reads/writes the
      persistent PostgreSQL-backed MLflow evaluation dataset.
3. **`harness`** ([`harness/`](harness/README.md)) — the evaluation suite:
    - **MLflow evaluation suite** (`mlflow-eval`) — evaluates agent-history data with
      `mlflow.genai.evaluate` scorers, with results browsable in the MLflow UI. It can evaluate a single ad-hoc report
      file, a single previously recorded run (by process instance ID, read from the MLflow dataset), or every recorded
      run at once — optionally collecting newly-completed runs first (`--collect`). It doesn't depend on the runner
      being active at evaluation time (only on the report file / trace data / dataset records already produced).

## Architecture

```
┌───────────────────────────┐        ┌──────────────────────────────────────┐
│  fluxnova-runner CLI      │        │  Agent's OTel instrumentation        │
│  (fluxnova-run)           │        │                                      │
│                           │        │  Emits gen_ai.* spans (invoke_agent, │
│  1. Deploy BPMN           │        │  execute_tool, chat) via OTLP        │
│     → Fluxnova engine     │        └───────────────────┬──────────────────┘
│  2. Start process         │                            │ OTLP
│     instance with input   │                            ▼
│     variables             │                 ┌────────────────────┐
│  3. Run mock external-    │                 │   OTel Collector   │
│     task workers          │                 └──────────┬─────────┘
│  4. Poll until process    │                            │ otlphttp exporter
│     completes             │                            ▼
│                           │              ┌────────────────────────────┐
└───────────────────────────┘              │  MLflow  /v1/traces        │
                                           │  (trace store)             │
                                           └──────────────┬─────────────┘
                                                          │ mlflow.search_traces()
                                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  mlflow-eval CLI  --collect  (on-demand pre-step; no background service)            │
│                                                                                     │
│  1. Find newly-completed invoke_agent traces for the configured subprocess_id       │
│  2. Join with BPMN (system prompt, tool input params) + Fluxnova core API           │
│     (final process variables, via /history/variable-instance)                       │
│  3. Upsert an agent-history record into the persistent MLflow evaluation dataset    │
│     (skip if already recorded)                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────────────────┐
│  mlflow-eval CLI                                                                        │
│                                                                                         │
│  Reads config YAML + agent-history JSON OR reads an existing MLflow dataset             │
│  record by --instance-id / --all                                                        │
│  Evaluates with MLflow scorers (Ollama / gemma4:e2b)                                    │
│  Outputs metrics summary; browse in the MLflow UI                                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

## GenAI observability (tracing & metrics)

The Fluxnova engine's `agentic-subprocess` plugin instruments each ad-hoc agent subprocess with OpenTelemetry signals in
the `gen_ai.*` namespace, under the instrumentation scope `org.finos.fluxnova.bpm.agentic`. They align with
the [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai), so any
OTLP-compatible backend (MLflow, Prometheus, Grafana, Datadog, …) consumes them without a vendor extension. The engine
only emits OTLP (gRPC `:4317` / HTTP `:4318`) via `fluxnova-engine-plugin-otel`; the OTel Collector fans it out to
downstream backends.

One subprocess execution drives three GenAI operations: `invoke_agent` (the whole agent loop),
`chat` (each LLM request/response), and `execute_tool` (each tool call).

### Metrics

| Metric                                | Instrument | Unit               | Emitted per                            | Key attributes                                                                                              |
|---------------------------------------|------------|--------------------|----------------------------------------|-------------------------------------------------------------------------------------------------------------|
| `gen_ai.client.token.usage`           | histogram  | `{token}`          | `chat` + `invoke_agent`                | `gen_ai.operation.name`, `gen_ai.token.type` (input/output), `gen_ai.provider.name`, `gen_ai.request.model` |
| `gen_ai.client.operation.duration`    | histogram  | `seconds`          | `chat`, `execute_tool`, `invoke_agent` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.tool.name`, `error.type`   |
| `gen_ai.invoke_agent.duration`        | histogram  | `seconds`          | subprocess execution                   | `gen_ai.agent.name`, `gen_ai.request.model`                                                                 |
| `gen_ai.invoke_agent.inference_calls` | histogram  | `{inference_call}` | subprocess execution                   | `gen_ai.agent.name`                                                                                         |
| `gen_ai.invoke_agent.tool_calls`      | histogram  | `{tool_call}`      | subprocess execution                   | `gen_ai.agent.name`                                                                                         |
| `gen_ai.execute_tool.duration`        | histogram  | `seconds`          | tool call                              | `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.agent.name`, `error.type`                                |

Streaming and server-side (model-host) metrics are not emitted — LLM calls here are synchronous request/response and
this module instruments the client/orchestrator side only.

### Traces

Each subprocess produces a span tree:

```
invoke_agent {gen_ai.agent.name}     type gen_ai.invoke_agent.internal (INTERNAL)
  chat {gen_ai.request.model}        type gen_ai.inference.client       (CLIENT)
  execute_tool {gen_ai.tool.name}    type gen_ai.execute_tool.internal  (INTERNAL)
  ...
```

- **`invoke_agent`** — `gen_ai.agent.name` (BPMN subprocess element id), `gen_ai.conversation.id`
  (process instance id), accumulated `gen_ai.usage.input_tokens`/`output_tokens`, and the per-run `inference_calls`/
  `tool_calls` counts (set at span end).
- **`chat`** — `gen_ai.request.model`/`response.model`, `gen_ai.provider.name`, per-call token usage.
- **`execute_tool`** — `gen_ai.tool.name`, `gen_ai.tool.call.id`, and `error.type` (`tool_error`) on failure. Note:
  `error.type`/`StatusCode.ERROR` is only set at the tool level; `invoke_agent` and
  `chat` spans always end `OK`.

### Content capture (opt-in)

Prompt/response/tool content — `gen_ai.system_instructions`, `gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.tool.call.arguments`/`.result` — is **disabled by default** (it may contain sensitive
data). Enable it via the Spring Boot property
`fluxnova.ai.agent.observability.capture-content: true` or the standard
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` environment variable.

## First time setup

This project assumes you're on **Windows**, using **[Podman](https://podman.io)** for all backing services (Fluxnova
engine, OTel Collector, MLflow), and **Git Bash** as your terminal — every command in this README uses forward-slash
(`/`) paths for that reason. (Backslashes work fine in native PowerShell/`cmd.exe`, but in Git Bash/MINGW64 they're
treated as escape characters and silently mangle paths, e.g. `config\loan-assesment.yml` → `configloan-assesment.yml`
— so forward slashes are used consistently here, since they work in both shells.)

1. **Install prerequisites:**
    - [Podman](https://podman.io/docs/installation), then start its VM: `podman machine init && podman machine start`
      ([Podman Desktop](https://podman-desktop.io) is recommended, though not required, for a GUI to view/manage pods,
      containers, and logs)
    - Python 3.11+
    - [Ollama](https://ollama.com) with `gemma4:e2b` (agent + offline `mlflow-eval` judge) and
      `qwen2.5:1.5b` (online `eval-service-worker` judge) pulled
      (`ollama pull gemma4:e2b && ollama pull qwen2.5:1.5b`)
    - The **Fluxnova** engine image — pull the public one from GHCR:
      `podman pull ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.0.0` (no login needed)

2. **Create the shared virtual environment** — run the setup script from the repo root. It creates one venv under
   `.venv` at the repo root and installs all three packages editable into it, so changes to any package take effect
   immediately without reinstalling:
   ```bash
   ./setup.sh
   ```
   Then activate it: `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (macOS/Linux).

   The script is idempotent (safe to re-run) and simply runs:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install --upgrade pip
   .venv/Scripts/python -m pip install -e "harness[dev]" -e "fluxnova-mlflow-dataset[dev]" -e "fluxnova-runner[dev]"
   ```
   Pass a specific interpreter (must be Python 3.11+) with `PYTHON=python3.11 ./setup.sh`. This installs four
   console-script entry points: `fluxnova-run` / `fluxnova-run-mock-workers` (runner), and `mlflow-eval` /
   `mlflow-judges` (harness evaluation suite).

3. **Start the backing services as Podman pods**, from Git Bash at the repo root:
   ```bash
   cd local-dev
   # .env's FLUXNOVA_IMAGE already points at the public GHCR image pulled above

   ./pods-up.sh   # start postgres, mlflow, fluxnova, eval-service (in dependency order)
   ```
   `pods-up.sh` is idempotent and orchestrates the per-service scripts in `local-dev/services/`
   (`postgres-up.sh` → `mlflow-up.sh` → `fluxnova-up.sh` → `eval-service-up.sh`); pass pod names to start only a subset
   (e.g. `./pods-up.sh postgres mlflow fluxnova`). The mlflow/fluxnova pods open their web UI in your default browser
   once ready. See
   [`local-dev/README.md`](local-dev/README.md) for the full pod details, the `eval-service-worker` pod, and
   Windows/WSL2 troubleshooting.

4. **(One-off) Register the MLflow AI Gateway judge endpoint** — required for automatic evaluation judges. See
   `local-dev/README.md`'s "MLflow AI Gateway endpoint for automatic evaluation judges" section.

You're now ready to run a workflow — see "Running `fluxnova-runner`" below.

## Running `fluxnova-runner` (Windows Git Bash)

From a Git Bash terminal, with the repo-root `.venv` activated (`source .venv/Scripts/activate` — see Installation above)
and your working directory at `harness/`:

```bash
fluxnova-run config/loan-assesment.yml --with-mock-workers
```

This deploys the BPMN, starts the process instance with the config's `variables`, runs mock external-task workers in the
background to complete each service task, and polls until the process finishes. It prints the **process instance ID** to
the terminal, e.g.:

```
Deploying bpmn/loan-assesment.bpmn …
  Deployed 'Loan Assessment' (id=...)
Starting process 'loanAssessmentProcess' …
  Instance ID: 3816567e-9f94-11f1-9ead-94b609a26547
Waiting for process to complete …
Process 3816567e-9f94-11f1-9ead-94b609a26547 completed.
Run 'mlflow-eval <config> --collect' to record the completed subprocess run into the MLflow evaluation dataset.
```

Other flags:

```bash
fluxnova-run --skip-deploy config/loan-assesment.yml   # BPMN already deployed
fluxnova-run config/loan-assesment.yml                 # no mock workers (needs real service-task workers/backends)
```

### Running the eval workflow (`config/loan-assesment-eval.yml`)

`bpmn/loan-assesment-eval.bpmn` (`loanAssessmentEvalProcess`) invokes the loan-assessment agent as a **Call Activity**
(`calledElement="loanAssessmentProcess"`) rather than embedding it, then runs a downstream eval/report/decision flow.
Because the called process lives in a separate file, both BPMNs must be deployed together — the eval config lists the
extra file under `additional_bpmn_paths`, which the runner posts in the same deployment:

```yaml
bpmn_path: bpmn/loan-assesment-eval.bpmn
additional_bpmn_paths:
  - bpmn/loan-assesment.bpmn        # the called loanAssessmentProcess
```

The eval process continues on the engine after the agent finishes (eval service task → decision gateway → human review
user tasks), which mock workers can't complete. To stop an unattended run hanging on those user tasks, set
`wait_for_activity` so the runner returns as soon as the agent Call Activity completes instead of waiting for the whole
process:

```yaml
wait_for_activity: CallActivity_LoanAssessmentAgent   # omit to wait for the entire process
```

```bash
fluxnova-run config/loan-assesment-eval.yml --with-mock-workers
```

The `--wait-for-activity ACTIVITY_ID` CLI flag overrides the config field for a single run. Scoring of the agent run is
handled asynchronously by the **eval-service-worker** (see `local-dev/README.md`), not by the runner.

### Then evaluate that run with `mlflow-eval` (This will become deprecated)

Make sure the MLflow tracking server is running first (see "Running the MLflow tracking server" below) and the OTel
Collector is exporting to it, then, still from `harness/`:

```bash
mlflow-eval config/loan-assesment.yml --collect --instance-id 3816567e-9f94-11f1-9ead-94b609a26547
```

`--collect` pulls that instance's completed trace out of MLflow's trace store, joins it with the BPMN and Fluxnova's
process-variable history, and records it into the persistent MLflow evaluation dataset; `--instance-id` then immediately
evaluates just that one record and prints the scorer summary to the terminal. See "Running the evaluations (MLflow)"
and "Collecting completed runs" below for the other modes (`--all`, `--collect` alone).

## Running the evaluations (MLflow)

`mlflow-eval` is the evaluation suite — config YAML scored with
the Ollama/gemma4:e2b judge model via `mlflow.genai.evaluate` scorers. It supports:

```bash
# 1. A single previously recorded run, read back from the MLflow dataset by process instance ID
mlflow-eval config/loan-assesment.yml --instance-id <instanceId>

# 2. Every run currently recorded in the MLflow dataset for this process_key
mlflow-eval config/loan-assesment.yml --all

# 3. --collect: pull newly-completed runs out of MLflow's trace store first (see below),
#    then evaluate. Can also be used on its own, with no evaluation selector, to only collect.
mlflow-eval config/loan-assesment.yml --collect --all
mlflow-eval config/loan-assesment.yml --collect
```

`mlflow-eval` only evaluates runs already recorded in the persistent MLflow dataset. Use `--collect` first (or on its
own) to populate the dataset from MLflow's trace store before evaluating.

Each of these prints an aggregate metrics summary to the terminal (MLflow's own `EvaluationResult.metrics`) and writes
full per-scorer results (scores, rationales, inputs/outputs) to a PostgreSQL-backed MLflow tracking store
(`postgres-local` pod's `mlflow` database — see `local-dev/services/postgres-up.sh`).

To view the results in the browser, use the same MLflow tracking server described in "Running the MLflow tracking
server" below (or, if you only need read-only browsing and aren't using `--collect`/OTel ingestion, the lighter-weight
`mlflow ui --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --port 5000` works too).

Then open [http://localhost:5000](http://localhost:5000) and open the `fluxnova-loanAssessmentProcess` experiment. Each
`mlflow-eval` run appears as a row; click into one to see per-scorer scores and rationales. Running
`mlflow-eval` again against other instances adds further rows to the same experiment for side-by-side comparison.

### Collecting completed runs (`mlflow-eval --collect`)

An OTel Collector exports traces straight to MLflow's own `/v1/traces` endpoint, so MLflow is the trace store.
`mlflow-eval --collect` is a lightweight, on-demand pre-step run each time you want fresh data:

1. Finds every `invoke_agent` trace for the config's `subprocess_id` in MLflow's trace store that isn't already recorded
   (idempotent — skips runs already present, matched by `processInstanceId`).
2. For each one, builds an agent-history report by joining that trace data with the static BPMN definition (system
   prompt, tool input params) and the run's final process variables (read from Fluxnova's
   `/history/variable-instance` API, which stays queryable long after the instance ends).
3. Upserts the result into the persistent MLflow evaluation dataset (`fluxnova-<process_key>` by default).

```bash
mlflow-eval config/loan-assesment.yml --collect
```

```
--collect: processInstanceId=... -> recorded (record_id=...)
```

You still need the OTel Collector configured to export directly to MLflow — add an `otlphttp` exporter pointing at
MLflow's `/v1/traces` endpoint and restart the Collector. `--collect` requires `subprocess_id` to be set in the workflow
config; the `mlflow_dataset.name`/`tracking_uri` config block (if present) is still honoured for where records get
written.

## Alternative: running the MLflow tracking server on the host

First-time setup above uses `local-dev/services/mlflow-up.sh` (a Podman pod) to run the MLflow tracking server. If you'd
rather run it as a host process instead (e.g. for IDE debugging), `mlflow-eval` can *read* the PostgreSQL store directly
(`postgresql://mlflow:mlflow@localhost:5432/mlflow`, provided `local-dev/services/postgres-up.sh` is running), but for
the OTel Collector to *write* traces into it, an actual MLflow tracking **server** (an HTTP process, not just the
library) must be running and listening on the URL the Collector's `otlphttp` exporter targets
(`http://localhost:5000/v1/traces` by default). `mlflow ui` alone does **not** accept incoming trace writes — it only
reads.

Start it (from the repo root, with the repo-root `.venv` activated and `local-dev/services/postgres-up.sh` already running)
and leave it running in its own terminal for as long as you want traces to be captured:

```bash
.venv/Scripts/mlflow server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --host 127.0.0.1 --port 5000
```

This single server also serves the browsable UI at [http://localhost:5000](http://localhost:5000), so once it's running
you no longer need a separate `mlflow ui` process pointed at the same store.

### As an IntelliJ Run/Debug Configuration

1. **Run → Edit Configurations… → + → Python** (requires the Python plugin).
2. **Name:** `MLflow Tracking Server`
3. **Run** (instead of "Script path"): choose **Module name** and set it to `mlflow`, *or* set "Script path" to
   `.venv/Scripts/mlflow.exe` (Windows) / `.venv/bin/mlflow` (macOS/Linux).
4. **Parameters:**
   ```
   server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --host 127.0.0.1 --port 5000
   ```
5. **Working directory:** `<repo root>/harness`
6. **Python interpreter:** the repo-root `.venv` interpreter (add it via **Add Interpreter → Existing** if not already
   registered).
7. Apply, then run this configuration before starting the OTel Collector or running `fluxnova-run` — leave it running in
   the background for the duration of your session.

## Local development with Podman (Fluxnova + OTel Collector + MLflow + PostgreSQL)

See [`local-dev/README.md`](local-dev/README.md) for the full details on running PostgreSQL, the Fluxnova engine, the
OTel Collector, MLflow, and the `eval-service-worker` as Podman pods for local development — including troubleshooting
notes and the MLflow AI Gateway judge-endpoint setup.

For **alternative run walkthroughs** (e.g. WSL with rootless Podman), see [`RUNNING-WSL.md`](RUNNING-WSL.md).

## Config file

All harness and evaluation behaviour is driven by a single YAML file.

[Example](config/loan-assesment.yml)

### `expected_tools` rule syntax

Each entry in `expected_tools` is a rule with:

| Key    | Required | Description                                                       |
|--------|----------|-------------------------------------------------------------------|
| `tool` | Yes      | Display name of the tool (must match `available_tools` values)    |
| `if`   | No       | Condition string — omit to make the tool unconditionally expected |

**Condition syntax:** `$variableName <op> <value>`

- `$variable` is resolved from `inputVariables` in the agent-history report at evaluation time
- Operators: `==` (equals), `!=` (not equals)
- Values: `"quoted string"`, `true`, `false`, or an integer

Examples:

```yaml
- if: '$applicantType == "EMPLOYED"'   # string comparison
- if: '$hasCollateral == true'          # boolean
- if: '$loanAmount != 0'               # integer
```

## Agent-history report format

The harness fetches this from the Fluxnova subprocess history endpoint and writes it as JSON:

```json
{
  "goal": "Perform a full loan risk assessment for applicant ...",
  "finalOutput": "APPROVE — the applicant meets all lending criteria ...",
  "iterations": 2,
  "inputVariables": {
    "applicantType": "EMPLOYED",
    "hasCollateral": false
  },
  "toolCalls": [
    {
      "toolName": "Check Credit Score",
      "toolElementId": "ServiceTask_CreditScoreCheck",
      "toolInput": "{\"customerId\": \"C001\"}",
      "status": "COMPLETED"
    }
  ],
  "promptMessages": [
    ...
  ],
  "executionTime": 4200
}
```

## Evaluation scorers (MLflow)

`harness/src/mlflow_eval/main.py` runs these checks over the agent-history data, added
after reviewing the BPMN's agent prompt and tool wiring:

| Scorer                                                | Type       | Description                                                                     |
|-------------------------------------------------------|------------|---------------------------------------------------------------------------------|
| `tool_correctness`                                    | Code       | Agent calls all expected tools and no inappropriate ones                        |
| `tool_argument_correctness`                           | Code       | Each expected tool receives the arguments the BPMN wires up for it              |
| `decision_quality`                                    | LLM judge  | Final output contains a clear, justified APPROVE/REJECT recommendation          |
| `evidence_citation`                                   | LLM judge  | Output cites fraud/affordability/income evidence (branches on `applicantType`)  |
| `matches_golden`                                      | LLM judge  | Output reaches the same decision as the matching golden scenario                |
| `no_collateral_check_when_no_collateral`              | Code       | Value Collateral is not called when `hasCollateral=false`                       |
| `collateral_valuation_called_correctly_when_required` | Code (new) | Value Collateral **is** called, with the correct `applicationId`, when required |
| `no_bank_statement_for_employed_applicant`            | Code       | Bank statements are not analysed for EMPLOYED applicants                        |
| `no_verify_employment_for_self_employed_applicant`    | Code (new) | Employment is not verified for non-EMPLOYED applicants                          |
| `all_tool_calls_completed`                            | Code       | Every initiated tool call reached COMPLETED status                              |
| `step_efficiency`                                     | Code       | Agent completes within a budget of loop iterations (+1 if collateral required)  |
| `requested_amount_passed_to_affordability`            | Code       | Affordability tool receives the correct `customerId` and `requestedAmount`      |
| `affordability_called_after_income_confirmed`         | Code (new) | Affordability is assessed only after income has been confirmed                  |

## Tech stack

| Component            | Technology                                                                                                                                            |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Workflow engine      | [Fluxnova](https://fluxnova.io) (Camunda-based)                                                                                                       |
| BPMN                 | Camunda BPMN 2.0                                                                                                                                      |
| Database             | PostgreSQL (Fluxnova process-engine datasource + MLflow tracking-server backend store, run as a Podman pod — see `local-dev/services/postgres-up.sh`) |
| Harness runtime      | Python 3.11, requests, PyYAML                                                                                                                         |
| Mock workers         | `camunda-external-task-client-python3`                                                                                                                |
| LLM agent            | Ollama / gemma4:e2b (runs inside Fluxnova)                                                                                                              |
| Evaluation framework | [MLflow GenAI evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/)                                                                         |
| Judge model          | Ollama / gemma4:e2b (offline `mlflow-eval`) · Ollama / qwen2.5:1.5b (online `eval-service-worker`, via the `fluxnova-judge` gateway endpoint)            |