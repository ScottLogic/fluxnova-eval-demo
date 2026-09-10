# Fluxnova Eval Demo

A set of tooling and an evaluation framework for Fluxnova workflows that include AI-driven agentic
subprocesses.

Goals of this project are:

- Create an Eval Test framework which facilitates Evaluation Driven Design (EDD). This will allow a demo of how you can
  build out an agentic workflow using EDD.
- Add an OTel collector and gen_ai* metrics and tracing with a suitable dashboard. This will allow a demo of real time
  production monitoring.
- Add an Eval task to production level process runs which will facilitate checks on responses and break-glass to a human
  in Production environments.

## Overview

This project is split into two shared Python packages plus standalone evaluation services:

1. **`fluxnova-runner`** ([`fluxnova-runner/`](fluxnova-runner/README.md)) — deploys a BPMN workflow to Fluxnova,
   starts a process instance with configurable input variables, drives mock external-task workers, and polls until
   the sub-process completes. Owns the workflow YAML config files ([`fluxnova-runner/config/`](fluxnova-runner/config)).
2. **`fluxnova-mlflow-dataset`** ([`fluxnova-mlflow-dataset/`](fluxnova-mlflow-dataset/README.md)) — a shared
   library providing the pieces the eval services reuse. It provides:
    - **trace reading** (`MlflowTraceReader`) — reads `gen_ai.*` span data (`invoke_agent`, `execute_tool`, `chat`)
      straight out of MLflow's trace store (populated by an OTel Collector exporting directly to MLflow).
    - **record shaping/read/write** — builds MLflow-dataset records from agent-history data and reads/writes the
      persistent PostgreSQL-backed MLflow evaluation dataset.
    - **shared scorer/judge definitions** (`scorers.py`) and the **`mlflow-judges`** CLI for toggling automatic
      (online) evaluation on/off.

The end-to-end **MLflow agent regression suite** ([`regression/`](regression/README.md)) sits alongside these packages
at the repo root: a gating check that drives the live agent per golden scenario and scores its real output with the
shared judges. See its [README](regression/README.md) for details.

Two standalone, independently-deployable **evaluation services** also live at the repo root, both scoring live agent
traces via the shared scorers (see each README for how they're deployed to Podman):

- **`eval-service-worker`** ([`eval-service-worker/`](eval-service-worker/README.md)) — a BPMN external-task worker that
  scores one just-completed run on demand (driven by the `loan-assesment-eval.bpmn` gateway).
- **`eval-trace-listener`** ([`eval-trace-listener/`](eval-trace-listener/README.md)) — an always-on service that tails
  the MLflow trace store and scores newly-completed runs of the configured agents with the deterministic (trace-only)
  scorers.

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
│  eval-trace-listener  (always-on service)                                           │
│                                                                                     │
│  1. Tail the trace store for newly-completed invoke_agent traces of configured      │
│     agents                                                                          │
│  2. Score each once with the shared deterministic (trace-only) scorers              │
│     (mlflow.genai.evaluate over the trace), logging Feedback back onto the trace    │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────────────────┐
│  eval-service-worker  (BPMN external-task worker)                                       │
│                                                                                         │
│  Triggered by the loan-assesment-eval.bpmn eval service task once the agent finishes    │
│  Scores that one run with the deterministic scorers + decision_quality judge            │
│  (Ollama / gemma4:e2b via the fluxnova-judge gateway); browse in the MLflow UI          │
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
treated as escape characters and silently mangle paths, e.g. `fluxnova-runner\config\loan-assesment.yml` → `fluxnova-runnerconfigloan-assesment.yml`
— so forward slashes are used consistently here, since they work in both shells.)

1. **Install prerequisites:**
    - [Podman](https://podman.io/docs/installation), then start its VM: `podman machine init && podman machine start`
      ([Podman Desktop](https://podman-desktop.io) is recommended, though not required, for a GUI to view/manage pods,
      containers, and logs)
    - Python 3.11+
    - [Ollama](https://ollama.com) with `gemma4:e2b` (agent + eval judge) and
      `qwen2.5:1.5b` (online `eval-service-worker` judge) pulled
      (`ollama pull gemma4:e2b && ollama pull qwen2.5:1.5b`)
    - The **Fluxnova** engine image — pull the public one from GHCR:
      `podman pull ghcr.io/dogle-scottlogic/fluxnova-edd-platform:1.0.0` (no login needed)

2. **Create the shared virtual environment** — run the setup script from the repo root. It creates one venv under
   `.venv` at the repo root and installs both packages editable into it, so changes to any package take effect
   immediately without reinstalling:
   ```bash
   ./setup.sh
   ```
   Then activate it: `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (macOS/Linux).

   The script is idempotent (safe to re-run) and simply runs:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install --upgrade pip
   .venv/Scripts/python -m pip install -e "fluxnova-mlflow-dataset[dev]" -e "fluxnova-runner[dev]"
   ```
   Pass a specific interpreter (must be Python 3.11+) with `PYTHON=python3.11 ./setup.sh`. This installs three
   console-script entry points: `fluxnova-run` / `fluxnova-run-mock-workers` (runner), and `mlflow-judges`
   (`fluxnova-mlflow-dataset`).

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
and your working directory at the repo root:

```bash
fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers
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
The completed subprocess run's trace is persisted in MLflow; the eval-trace-listener service (if running) will score it automatically.
```

Other flags:

```bash
fluxnova-run --skip-deploy fluxnova-runner/config/loan-assesment.yml   # BPMN already deployed
fluxnova-run fluxnova-runner/config/loan-assesment.yml                 # no mock workers (needs real service-task workers/backends)
```

### Running the eval workflow (`fluxnova-runner/config/loan-assesment-eval.yml`)

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
fluxnova-run fluxnova-runner/config/loan-assesment-eval.yml --with-mock-workers
```

The `--wait-for-activity ACTIVITY_ID` CLI flag overrides the config field for a single run. Scoring of the agent run is
handled asynchronously by the **eval-service-worker** (see `local-dev/README.md`), not by the runner.

## Evaluating agent runs

Evaluation is no longer a manual batch step — it happens automatically off the agent traces the OTel Collector exports
into MLflow. There are three complementary paths, all using the **shared scorers/judges** in
`fluxnova_mlflow_dataset.scorers` so they never disagree on what "good" means:

- **`eval-trace-listener`** (always-on service) — tails MLflow's trace store and scores each newly-completed run of the
  configured agents once with the deterministic (trace-only) scorers, logging `Feedback` back onto the trace. Best for
  passive, continuous scoring of every run as it lands. See [`eval-trace-listener/README.md`](eval-trace-listener/README.md).
- **`eval-service-worker`** (BPMN external-task worker) — triggered by the eval service task in
  `loan-assesment-eval.bpmn` once the agent Call Activity finishes, it scores that one run with the deterministic
  scorers **plus** the `decision_quality` LLM judge (via the `fluxnova-judge` MLflow AI Gateway endpoint). Best for
  synchronous, in-process scoring wired into the workflow. See [`eval-service-worker/README.md`](eval-service-worker/README.md).
- **`regression/`** (pytest gating suite) — drives the live agent per golden scenario and asserts its real output
  satisfies the shared `decision_quality` and `matches_golden` judges plus the deterministic
  `definitive_decision_stated` scorer. Best as a CI gate against behavioural
  regressions. See [`regression/README.md`](regression/README.md).

All three write their results to the same PostgreSQL-backed MLflow tracking store (`postgres-local` pod's `mlflow`
database — see `local-dev/services/postgres-up.sh`).

### Automatic (online) evaluation: `mlflow-judges`

For **online** evaluation — where the MLflow server itself scores a sampled fraction of new traces with no code running
continuously — use the `mlflow-judges` CLI (from `fluxnova-mlflow-dataset`) to register/start/stop the automatic judges.
See [`fluxnova-mlflow-dataset/README.md`](fluxnova-mlflow-dataset/README.md#mlflow-judges-toggling-automatic-online-evaluation)
and `local-dev/README.md`'s AI-Gateway section for the one-off endpoint setup this depends on.

To view the results in the browser, use the same MLflow tracking server described in "Running the MLflow tracking
server" below (or, if you only need read-only browsing and aren't ingesting new traces, the lighter-weight
`mlflow ui --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --port 5000` works too).

Then open [http://localhost:5000](http://localhost:5000) and open the `fluxnova-loanAssessmentProcess` experiment. Each
evaluation run appears as a row; click into one to see per-scorer scores and rationales. Scoring further runs adds
more rows to the same experiment for side-by-side comparison.

## Alternative: running the MLflow tracking server on the host

First-time setup above uses `local-dev/services/mlflow-up.sh` (a Podman pod) to run the MLflow tracking server. If you'd
rather run it as a host process instead (e.g. for IDE debugging), an MLflow client can *read* the PostgreSQL store directly
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
5. **Working directory:** `<repo root>`
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

All runner and evaluation behaviour is driven by a single YAML file.

[Example](fluxnova-runner/config/loan-assesment.yml)

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

`fluxnova-mlflow-dataset` builds this from the Fluxnova subprocess history endpoint and MLflow trace data as JSON:

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

`fluxnova_mlflow_dataset.scorers` is the single source of truth for every scorer.
Each one is **decoupled from tracing** — it takes plain `inputs` / `outputs` /
`expectations` values and never reads a span itself, so each consumer is free to
source that data wherever suits it (live agent output, a trace, process
variables). The scorers split into two families:

- **Code** (deterministic) — pure Python checks over tool calls / output text.
- **LLM judge** (non-deterministic) — grade the output with a judge model.

They are grouped into reusable bundles:

- `DETERMINISTIC_SCORERS` — the 10 code scorers below that need only tool
  *names* / status / input-variables / output text (no captured arguments).
- `TOOL_ARGUMENT_SCORERS` — 3 opt-in code scorers that also inspect tool-call
  *arguments*; only meaningful when content capture is on (they self-skip with
  `Feedback(None)` otherwise). Not run by any consumer by default.
- `ALL_DETERMINISTIC_SCORERS` = `DETERMINISTIC_SCORERS` + `TOOL_ARGUMENT_SCORERS`.

**Consumers:** **R** = `regression` (live agent) · **W** = `eval-service-worker`
(online, per-run) · **L** = `eval-trace-listener` (offline, per-trace). See each
service's README for exactly how it sources the scorer inputs.

| Scorer                                                | Type      | Bundle              | What it checks                                                              | Consumers |
|-------------------------------------------------------|-----------|---------------------|----------------------------------------------------------------------------|-----------|
| `required_tools_called`                               | Code      | DETERMINISTIC       | Every tool the scenario requires was called                                | W · L     |
| `no_tool_errors`                                      | Code      | DETERMINISTIC       | No tool call ended in an error/failed status                               | W · L     |
| `definitive_decision_stated`                          | Code      | DETERMINISTIC       | Output literally states an APPROVE/REJECT decision                         | R · W · L |
| `tool_correctness`                                    | Code      | DETERMINISTIC       | Agent calls all expected tools and no inappropriate ones                   | W · L     |
| `all_tool_calls_completed`                            | Code      | DETERMINISTIC       | Every initiated tool call reached a completed status                      | W · L     |
| `no_collateral_check_when_no_collateral`              | Code      | DETERMINISTIC       | Value Collateral is not called when `hasCollateral=false`                  | W · L     |
| `no_bank_statement_for_employed_applicant`            | Code      | DETERMINISTIC       | Bank statements are not analysed for EMPLOYED applicants                   | W · L     |
| `no_verify_employment_for_self_employed_applicant`    | Code      | DETERMINISTIC       | Employment is not verified for non-EMPLOYED applicants                     | W · L     |
| `step_efficiency`                                     | Code      | DETERMINISTIC       | Agent completes within a budget of loop iterations (+1 if collateral)      | W · L     |
| `affordability_called_after_income_confirmed`         | Code      | DETERMINISTIC       | Affordability is assessed only after income has been confirmed             | W · L     |
| `tool_argument_correctness`                           | Code      | TOOL_ARGUMENT       | Each expected tool receives the arguments the BPMN wires up for it         | —         |
| `collateral_valuation_called_correctly_when_required` | Code      | TOOL_ARGUMENT       | Value Collateral **is** called, with the correct `applicationId`, when required | —    |
| `requested_amount_passed_to_affordability`            | Code      | TOOL_ARGUMENT       | Affordability tool receives the correct `customerId` and `requestedAmount` | —         |
| `decision_quality`                                    | LLM judge | —                   | Final output is a clear, justified APPROVE/REJECT recommendation           | R · W · L |
| `evidence_citation`                                   | LLM judge | —                   | Output grounds its reasoning in the applicant/tool evidence (graded 0–1)   | R · L     |
| `matches_golden`                                      | LLM judge | —                   | Output reaches the same decision as the matching golden (needs `expected_output`) | R |

Notes:
- `matches_golden` requires a golden `expected_output` (an `expectations`
  value), so only the **regression** suite runs it — a bare trace doesn't carry
  it, so `W`/`L` cannot.
- `evidence_citation` treats the Fluxnova-only `agent_goal` as *optional*
  context (it isn't on the MLflow trace), so it can run trace-side in `L`.
- The three LLM judges use an Ollama judge model; `eval-service-worker` reaches
  it via the `fluxnova-judge` gateway endpoint, while `regression` and
  `eval-trace-listener` call Ollama directly.

## Tech stack

| Component            | Technology                                                                                                                                            |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Workflow engine      | [Fluxnova](https://fluxnova.io) (Camunda-based)                                                                                                       |
| BPMN                 | Camunda BPMN 2.0                                                                                                                                      |
| Database             | PostgreSQL (Fluxnova process-engine datasource + MLflow tracking-server backend store, run as a Podman pod — see `local-dev/services/postgres-up.sh`) |
| Python runtime       | Python 3.11, requests, PyYAML                                                                                                                         |
| Mock workers         | `camunda-external-task-client-python3`                                                                                                                |
| LLM agent            | Ollama / gemma4:e2b (runs inside Fluxnova)                                                                                                              |
| Evaluation framework | [MLflow GenAI evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/)                                                                         |
| Judge model          | Ollama / gemma4:e2b (regression + eval services) · Ollama / qwen2.5:1.5b (online `eval-service-worker`, via the `fluxnova-judge` gateway endpoint)            |