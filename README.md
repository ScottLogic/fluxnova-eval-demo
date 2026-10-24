# Fluxnova Evals Demo

A set of tooling and evals to demonstrate the use of agentic evaluation with Fluxnova workflows.

**Run locally on macOS:** follow [RUNNING-MACOS.md](RUNNING-MACOS.md) for setup,
demo execution and step-by-step validation. Windows Git Bash and macOS share the
Python environment and Podman service configuration.

Goals of this project are:

- Create an Eval Test framework which facilitates Evaluation Driven Design (EDD). This will demonstrate how you can
  build out an agentic workflow using EDD.
- Add an OTel collector and gen_ai* metrics and tracing with a suitable dashboard. This will allow a demo of real time
  production monitoring.
- Add an Eval task to production level process runs which will facilitate checks on responses and break-glass to a human
  in Production environments.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
  - [bpmn](#--bpmn)
  - [cicd](#--cicd)
  - [datasets](#--datasets)
  - [eval-service-worker](#--eval-service-worker)
  - [eval-trace-listener](#--eval-trace-listener)
  - [fluxnova-mlflow-dataset](#--fluxnova-mlflow-dataset)
  - [fluxnova-runner](#--fluxnova-runner)
  - [local-dev](#--local-dev)
  - [model-benchmarks](#--model-benchmarks)
  - [regression](#--regression)
- [Evaluation scorers (MLflow)](#evaluation-scorers-mlflow)
- [GenAI observability (tracing & metrics)](#genai-observability-tracing--metrics)
    - [Metrics](#metrics)
    - [Traces](#traces)
    - [Content capture (opt-in)](#content-capture-opt-in)
- [First time setup](#first-time-setup)
- [Running `fluxnova-runner`](#running-fluxnova-runner)
    - [Running the eval workflow](#running-the-eval-workflow-fluxnova-runnerconfigloan-assesment-evalyml)
- [Evaluating agent runs](#evaluating-agent-runs)
    - [Automatic (online) evaluation: `mlflow-judges`](#automatic-online-evaluation-mlflow-judges)
- [Alternative: running the MLflow tracking server on the host](#alternative-running-the-mlflow-tracking-server-on-the-host)
    - [As an IntelliJ Run/Debug Configuration](#as-an-intellij-rundebug-configuration)
- [Local development with Podman](#local-development-with-podman-fluxnova--otel-collector--mlflow--postgresql)
- [Config file](#config-file)
    - [`expected_tools` rule syntax](#expected_tools-rule-syntax)
- [Agent-history report format](#agent-history-report-format)
- [Tech stack](#tech-stack)

## Overview

This project is split into two several Python packages which are designed to run locally in podman. There are two main
flows which make up the standard use-cases.

1. Production demo.
    - Deploy and initiate a bpmn via the [fluxnova-runner](fluxnova-runner).
    - Observe the tracing in MLFlow.
    - The [eval-trace-listener](eval-trace-listener) will automatically run evals against configured traces as they
      arrive in MLFlow
    - Handle real time guard-rail use-cases with a Service Worker and the [eval-service-worker](eval-service-worker)
      service.
2. Development Demo
    - Run a complete regression suite using the [regression tests](regression).

Together these two use-case demonstrate both development using an EDD approach of a Fluxnova processes and the live
monitoring and evaluation of agentic workflows in Fluxnova via MLFlow.

The end-to-end **MLflow agent regression suite** ([`regression/`](regression/README.md)) sits alongside these packages
at the repo root: a gating check that drives the live agent per golden scenario and scores its real output with the
shared judges. See its [README](regression/README.md) for details.

## Architecture

See [architecture diagram](Fluxnova%20EDD.png).

## Repository Structure

This repository consists of the following:

### -| [bpmn](bpmn)

This directory contains the BPMN diagrams used by the project. Agentic subprocesses are defined in their own BPMN files
and invoked by broader business workflows through Call Activities. This keeps the agentic functionality isolated, so it
can be developed, tested, and evaluated independently while remaining reusable within end-to-end processes. The loan
assessment workflow is an example of this pattern.

### -| [cicd](cicd)

Unused. This is a placeholder for building out CICD pipelines (GitLab for example)

### -| [datasets](datasets)

Contains JSON golden datasets: A list of representative agent scenarios, each with an `input`, reference
`expected_output`, human-readable `context`, and `additional_metadata` for identifying the scenario. For end-to-end
regression testing, each golden is extended with `input_variables` (the process variables used to start the workflow)
and `tool_responses` (the deterministic responses replayed by mock external-task workers). This lets the regression
suite execute the live agent for the same scenario and compare its actual output with the reference output using
Fluxnova.

### -| [eval-service-worker](eval-service-worker)

A BPMN external-task worker that synchronously scores a just-completed agentic subprocess run on demand. It reads the
run's MLflow trace, evaluates the final output with the `decision_quality` LLM judge and deterministic trace-based
scorers, and stores each scorer's feedback in MLflow. The evaluation passes only when every scorer passes. It returns
`evalPassed` and `evalRationale` workflow variables, which subsequent BPMN steps can use to continue automatically or
route the work for human review.

More detail available in the [README](eval-service-worker/README.md).

### -| [eval-trace-listener](eval-trace-listener)

An always-on, asynchronous service that polls a configured MLflow experiment for completed runs of configured agents.
It extracts the scorer inputs and final output directly from each trace, runs deterministic trace-based scorers plus the
`decision_quality` and `evidence_citation` LLM judges, and records the resulting feedback on the same trace in MLflow.
It avoids rescoring traces, including after a restart. This is an observational, non-blocking service: it does not
return workflow variables or alter the flow of the underlying process.

More detail available in the [README](eval-trace-listener/README.md).

### -| [fluxnova-mlflow-dataset](fluxnova-mlflow-dataset)

An installable library providing MLflow-specific functionality for reuse across the evaluation services and regression
suite. It provides:

- **Trace reading**: Reads `gen_ai.*` span data (`invoke_agent`, `execute_tool`, `chat`) straight out of MLflow's trace
  store (populated by an OTel Collector exporting directly to MLflow).
- **Record shaping/read/write**: Builds MLflow-dataset records from agent-history data and reads/writes the
  persistent PostgreSQL-backed MLflow evaluation dataset.
- **Shared scorer and judge definitions** (`scorers.py`) and the **`mlflow-judges`** CLI for managing automatic online
  evaluation.

Keeping this logic in one package ensures every consumer evaluates agent runs using the same data shape and criteria.

More detail available in the [README](fluxnova-mlflow-dataset/README.md).

### -| [fluxnova-runner](fluxnova-runner)

A Python service for deploying and executing Fluxnova workflows. It reads
a [workflow YAML configuration](fluxnova-runner/config), deploys the
primary BPMN and any additional BPMN resources required by Call Activities, then starts a process instance with the
configured input variables. It can optionally run mock external-task workers, allowing workflows to be exercised
locally without their real downstream service backends.

The runner can wait for either the complete process or a named BPMN activity, which supports workflows that continue
into human or asynchronous stages. It is responsible only for deployment and execution; evaluation is performed
afterwards by the `eval-trace-listener` or `eval-service-worker`.

More detail available in the [README](fluxnova-runner/README.md).

### -| [local-dev](local-dev)

Local Podman configuration and scripts for running the complete development environment: PostgreSQL, Fluxnova with an
OTel Collector, MLflow, the evaluation services, and optional Prometheus and Grafana observability tooling. The
`pods-up.sh` and `pods-down.sh` scripts start and stop these services in dependency order, while `compose.yaml` provides
an equivalent Podman Compose setup. This directory also contains the shared environment, engine, collector, database,
and dashboard configuration used by the local stack.

More detail available in the [README](local-dev/README.md).

### -| [model-benchmarks](model-benchmarks)

Benchmark data and reporting for comparing locally hosted models on agentic tool-calling behaviour. The capture script
records OpenTelemetry `gen_ai.*` metrics before and after a workflow run; the raw JSON snapshots, machine-readable
summary, and results report preserve the resulting tool-call, inference-call, token-usage, error, and approximate
duration measurements. The current benchmark uses the loan-assessment workflow as an example and measures behavioural
tool-calling metrics only; it does not include LLM-judge quality scores.

### -| [regression](regression)

An end-to-end pytest regression suite that acts as a quality gate for agentic workflows. For each golden scenario, it
uses the runner to execute the live agent with the scenario's input variables and deterministic mock tool responses,
then evaluates its actual final output using the shared MLflow scorers and judges. The suite checks for a clear,
evidence-backed decision, agreement with the golden reference output, and required decision content, helping detect
behavioural regressions before a workflow change is released.

More detail available in the [README](regression/README.md).

## Evaluation scorers (MLflow)

`fluxnova_mlflow_dataset.scorers` is the single source of truth for every scorer.
Each one is **decoupled from tracing** — it takes plain `inputs` / `outputs` /
`expectations` values and never reads a span itself, so each consumer is free to
source that data wherever suits it (live agent output, a trace, process
variables). The scorers split into two families:

- **Code** (deterministic) — pure Python checks over tool calls / output text.
- **LLM judge** (non-deterministic) — grade the output with a judge model.

They are grouped into reusable bundles:

- `DETERMINISTIC_SCORERS` — the 10 code scorers below that need only tool *names* / status / input-variables / output
  text (no captured arguments).
- `TOOL_ARGUMENT_SCORERS` — 3 opt-in code scorers that also inspect tool-call *arguments*; only meaningful when content
  capture is on (they self-skip with
  `Feedback(None)` otherwise). Not run by any consumer by default.
- `ALL_DETERMINISTIC_SCORERS` = `DETERMINISTIC_SCORERS` + `TOOL_ARGUMENT_SCORERS`.

**Consumers:** **R** = `regression` (live agent) · **W** = `eval-service-worker`
(online, per-run) · **L** = `eval-trace-listener` (offline, per-trace). See each
service's README for exactly how it sources the scorer inputs.

| Scorer                                                | Type      | Bundle        | What it checks                                                                    | Consumers |
|-------------------------------------------------------|-----------|---------------|-----------------------------------------------------------------------------------|-----------|
| `required_tools_called`                               | Code      | DETERMINISTIC | Every tool the scenario requires was called                                       | W · L     |
| `no_tool_errors`                                      | Code      | DETERMINISTIC | No tool call ended in an error/failed status                                      | W · L     |
| `definitive_decision_stated`                          | Code      | DETERMINISTIC | Output literally states an APPROVE/REJECT decision                                | R · W · L |
| `tool_correctness`                                    | Code      | DETERMINISTIC | Agent calls all expected tools and no inappropriate ones                          | W · L     |
| `all_tool_calls_completed`                            | Code      | DETERMINISTIC | Every initiated tool call reached a completed status                              | W · L     |
| `no_collateral_check_when_no_collateral`              | Code      | DETERMINISTIC | Value Collateral is not called when `hasCollateral=false`                         | W · L     |
| `no_bank_statement_for_employed_applicant`            | Code      | DETERMINISTIC | Bank statements are not analysed for EMPLOYED applicants                          | W · L     |
| `no_verify_employment_for_self_employed_applicant`    | Code      | DETERMINISTIC | Employment is not verified for non-EMPLOYED applicants                            | W · L     |
| `step_efficiency`                                     | Code      | DETERMINISTIC | Agent completes within a budget of loop iterations (+1 if collateral)             | W · L     |
| `affordability_called_after_income_confirmed`         | Code      | DETERMINISTIC | Affordability is assessed only after income has been confirmed                    | W · L     |
| `tool_argument_correctness`                           | Code      | TOOL_ARGUMENT | Each expected tool receives the arguments the BPMN wires up for it                | —         |
| `collateral_valuation_called_correctly_when_required` | Code      | TOOL_ARGUMENT | Value Collateral **is** called, with the correct `applicationId`, when required   | —         |
| `requested_amount_passed_to_affordability`            | Code      | TOOL_ARGUMENT | Affordability tool receives the correct `customerId` and `requestedAmount`        | —         |
| `decision_quality`                                    | LLM judge | —             | Final output is a clear, justified APPROVE/REJECT recommendation                  | R · W · L |
| `evidence_citation`                                   | LLM judge | —             | Output grounds its reasoning in the applicant/tool evidence (graded 0–1)          | R · L     |
| `matches_golden`                                      | LLM judge | —             | Output reaches the same decision as the matching golden (needs `expected_output`) | R         |

Notes:

- `matches_golden` requires a golden `expected_output` (an `expectations`
  value), so only the **regression** suite runs it — a bare trace doesn't carry
  it, so `W`/`L` cannot.
- `evidence_citation` treats the Fluxnova-only `agent_goal` as *optional*
  context (it isn't on the MLflow trace), so it can run trace-side in `L`.
- Local demo judges default to OpenAI `gpt-4o-mini`; select Ollama with the shared
  provider configuration. The demo worker calls the configured model directly.
  Gateway-backed automatic sampling remains available as an optional setup.

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

Use **macOS Terminal**, **Windows Git Bash**, or a Linux shell. Commands use forward
slashes on every OS. Install Python 3.11+ and [Podman](https://podman.io/docs/installation)
with a running VM on macOS/Windows. Apple Silicon also needs x86 execution support
for the current AMD64-only Fluxnova image; see the [Mac guide](RUNNING-MACOS.md).

From the repository root:

```bash
./setup.sh                         # installs all four packages editable, with dev dependencies
source .venv/bin/activate           # macOS/Linux
# source .venv/Scripts/activate     # Windows Git Bash
cp local-dev/.env.example local-dev/.env  # first time only
```

Set `OPENAI_API_KEY` in `local-dev/.env`. The default demo uses OpenAI for the
agent and judges; Ollama is optional. Startup pulls the configured public images.
Choose a specific interpreter with `PYTHON=python3.11 ./setup.sh` if needed.

```bash
./local-dev/pods-up.sh postgres mlflow fluxnova
./local-dev/pods-up.sh eval-service eval-listener observability
set -a
source local-dev/.env
set +a
```

MLflow creates/resolves the trace experiment automatically. The default worker
calls the judge directly; a gateway endpoint is only needed for optional automatic
sampling. See [local-dev/README.md](local-dev/README.md) for networking, Compose,
provider configuration, persistence and host debugging.

## Running `fluxnova-runner`

With the shared `.venv` active and `local-dev/.env` exported as above, run from the repository root:

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

Evaluation happens automatically off the agent traces the OTel Collector exports into MLflow. There are three
complementary paths, all using the **shared scorers/judges** in
`fluxnova_mlflow_dataset.scorers` so they never disagree on what "good" means:

- **`eval-trace-listener`** (always-on service) — tails MLflow's trace store and scores each newly-completed run of the
  configured agents with deterministic checks plus `decision_quality` and `evidence_citation`, logging `Feedback` back onto the trace. Best for
  passive, continuous scoring of every run as it lands. See [
  `eval-trace-listener/README.md`](eval-trace-listener/README.md).
- **`eval-service-worker`** (BPMN external-task worker) — triggered by the eval service task in
  `loan-assesment-eval.bpmn` once the agent Call Activity finishes, it scores that one run with the deterministic
  scorers **plus** the `decision_quality` LLM judge (direct OpenAI in the default demo; optionally via an AI Gateway). Best for
  synchronous, in-process scoring wired into the workflow. See [
  `eval-service-worker/README.md`](eval-service-worker/README.md).
- **`regression/`** (pytest gating suite) — drives the live agent per golden scenario via MLflow's `predict_fn`
  pattern and asserts its real output satisfies the shared `decision_quality` and `matches_golden` judges, the
  `evidence_citation` judge, and the full `ALL_DETERMINISTIC_SCORERS` bundle. Best as a CI gate against behavioural
  regressions. See [`regression/README.md`](regression/README.md).

All three write their results to the same PostgreSQL-backed MLflow tracking store (`postgres-local` pod's `mlflow`
database — see `local-dev/services/postgres-up.sh`).

### Automatic (online) evaluation: `mlflow-judges`

For **online** evaluation — where the MLflow server itself scores a sampled fraction of new traces with no code running
continuously — use the `mlflow-judges` CLI (from `fluxnova-mlflow-dataset`) to register/start/stop the automatic judges.
See [
`fluxnova-mlflow-dataset/README.md`](fluxnova-mlflow-dataset/README.md#mlflow-judges-toggling-automatic-online-evaluation)
and `local-dev/README.md`'s AI-Gateway section for the one-off endpoint setup this depends on.

To view the results in the browser, use the same MLflow tracking server described in "Running the MLflow tracking
server" below (or, if you only need read-only browsing and aren't ingesting new traces, the lighter-weight
`mlflow ui --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --port 5000` works too).

Then open [http://localhost:5000](http://localhost:5000) (or your configured port) and open the experiment named by
`EVAL_SERVICE_EXPERIMENT_NAME` (default `fluxnova-loanAssessmentEvalProcess`). Each
evaluation run appears as a row; click into one to see per-scorer scores and rationales. Scoring further runs adds
more rows to the same experiment for side-by-side comparison.

## Alternative: running the MLflow tracking server on the host

First-time setup above uses `local-dev/services/mlflow-up.sh` (a Podman pod) to run the MLflow tracking server. If you'd
rather run it as a host process instead (e.g. for IDE debugging), an MLflow client can *read* the PostgreSQL store
directly (`postgresql://mlflow:mlflow@localhost:5432/mlflow`, provided `local-dev/services/postgres-up.sh` is running),
but for
the OTel Collector to *write* traces into it, an actual MLflow tracking **server** (an HTTP process, not just the
library) must be running and listening on the URL the Collector's `otlphttp` exporter targets
(`MLFLOW_OTLP_ENDPOINT`, normally an internal service URL in the managed stack). `mlflow ui` alone does **not** accept incoming trace writes — it only
reads.

Start it (from the repo root, with the repo-root `.venv` activated and `local-dev/services/postgres-up.sh` already
running)
and leave it running in its own terminal for as long as you want traces to be captured:

```bash
python -m mlflow server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --host 0.0.0.0 --port 5000
```

This single server also serves the browsable UI at [http://localhost:5000](http://localhost:5000), so once it's running
you no longer need a separate `mlflow ui` process pointed at the same store.

For trace ingestion into a host-run server, also run `local-dev/mlflow/bootstrap.py`
against that server and mount its generated header map into the collector at
`/mlflow-runtime/headers.yaml`, with `MLFLOW_OTLP_ENDPOINT` reaching the host via
`host.containers.internal`. The managed stack handles this automatically; use it
for the demo and debug the editable Python services on the host.

### As an IntelliJ Run/Debug Configuration

1. **Run → Edit Configurations… → + → Python** (requires the Python plugin).
2. **Name:** `MLflow Tracking Server`
3. **Run** (instead of "Script path"): choose **Module name** and set it to `mlflow`, *or* set "Script path" to
   `.venv/Scripts/mlflow.exe` (Windows) / `.venv/bin/mlflow` (macOS/Linux).
4. **Parameters:**
   ```
    server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --host 0.0.0.0 --port 5000
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

For walkthroughs see [macOS](RUNNING-MACOS.md) and [WSL](RUNNING-WSL.md).

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
  ],
  "executionTime": 4200
}
```

## Tech stack

| Component            | Technology                                                                                                                                            |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| Workflow engine      | [Fluxnova](https://fluxnova.io) (Camunda-based)                                                                                                       |
| BPMN                 | Camunda BPMN 2.0                                                                                                                                      |
| Database             | PostgreSQL (Fluxnova process-engine datasource + MLflow tracking-server backend store, run as a Podman pod — see `local-dev/services/postgres-up.sh`) |
| Python runtime       | Python 3.11, requests, PyYAML                                                                                                                         |
| Mock workers         | `camunda-external-task-client-python3`                                                                                                                |
| LLM agent            | OpenAI / gpt-4o (default, runs inside Fluxnova) — see [local-dev/README.md](local-dev/README.md#bpmn-agent-llm-provider-openai-default-ollama-alternative) for using Ollama / gemma4:e2b instead |
| Evaluation framework | [MLflow GenAI evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/)                                                                         |
| Judge model          | OpenAI / gpt-4o-mini by default; optional native Ollama / gemma4:e2b; AI Gateway available for automatic sampling |
