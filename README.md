# Fluxnova Evals Demo

A set of tooling and evals to demonstrate the use of agentic evaluation with Fluxnova workflows.

Start with the [local development guide](local-dev/README.md) for macOS, Windows
Git Bash and Linux/WSL setup, demo execution and troubleshooting. Use the
[regression guide](regression/README.md) for testing, judge calibration and report replay.

Goals of this project are:

- Create an Eval Test framework which facilitates Evaluation Driven Design (EDD). This will demonstrate how you can
  build out an agentic workflow using EDD.
- Add an OTel collector and gen_ai* metrics and tracing with a suitable dashboard. This will allow a demo of real time
  production monitoring.
- Add Eval tasks to production level process runs: a blocking guardrail which can break-glass to a human, and a
  non-blocking Eval which scores every run without holding up the process.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
  - [bpmn](#--bpmn)
  - [cicd](#--cicd)
  - [datasets](#--datasets)
  - [eval-service-worker](#--eval-service-worker)
  - [eval-async-worker](#--eval-async-worker)
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
- [Where eval data lives](#where-eval-data-lives)
- [First time setup](#first-time-setup)
- [Running `fluxnova-runner`](#running-fluxnova-runner)
    - [Running the loan approval workflow](#running-the-loan-approval-workflow-fluxnova-runnerconfigloan_approval_process_aiyml)
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

This project has four Python packages and backing services designed to run locally with Podman. There are two main
flows which make up the standard use-cases.

1. Production demo.
    - Deploy and initiate a bpmn via the [fluxnova-runner](fluxnova-runner).
    - Observe the tracing in MLFlow.
    - A non-blocking Eval service task, served by the [eval-async-worker](eval-async-worker), scores every run
      without holding up the process.
    - A blocking guardrail Eval service task, served by the [eval-service-worker](eval-service-worker), routes runs
      that fail evaluation to human review.
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

The external-task worker for the blocking guardrail Eval service task (`ServiceTask_EvaluateAgentOutput`, topic
`agent-output-eval`). It synchronously scores a just-completed agentic subprocess run. It reads the
run's MLflow trace, evaluates the final output with the `decision_quality` LLM judge and deterministic trace-based
scorers, and stores each scorer's feedback in MLflow. The evaluation passes only when every scorer passes. It returns
`evalPassed` and `evalRationale` workflow variables, which subsequent BPMN steps can use to continue automatically or
route the work for human review.

More detail available in the [README](eval-service-worker/README.md).

### -| [eval-async-worker](eval-async-worker)

The external-task worker for the non-blocking Eval service task (`ServiceTask_AsyncEvaluateAgentOutput`, topic
`agent-output-eval-async`). `LoanApprovalProcess_AI.bpmn` forks after the agent call, and this task sits on its own
branch, so scoring never holds up the loan decision. For each task it reads the agent run's trace, runs the
deterministic scorers plus the `decision_quality` and `evidence_citation` LLM judges, and records the feedback on the
same trace in MLflow. It completes the task without returning workflow variables, so it never alters the flow of the
process. A live sample rate controls what fraction of runs are scored.

More detail available in the [README](eval-async-worker/README.md).

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
afterwards by the `eval-async-worker` or `eval-service-worker`.

More detail available in the [README](fluxnova-runner/README.md).

### -| [local-dev](local-dev)

Local Podman configuration and scripts for running the complete development environment: PostgreSQL, Fluxnova with an
OTel Collector, MLflow, frontend/UI API, the evaluation services, and optional Prometheus and Grafana observability tooling. The
`pods-up.sh` and `pods-down.sh` scripts start and stop these services in dependency order, while `compose.yaml` provides
an equivalent Podman Compose setup. This directory also contains the shared environment, engine, collector, database,
and dashboard configuration used by the local stack.

More detail available in the [README](local-dev/README.md).

### -| [frontend](frontend) and [ui-api](ui-api)

The React/Vite demo UI is served by nginx and backed by a FastAPI service. It
starts workflows, displays nested progress and agent configuration, runs the six
golden regression scenarios with per-scorer results.
Both are included in the local stack; see the [UI walkthrough](local-dev/README.md#frontend-and-ui-api).

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

- `DETERMINISTIC_SCORERS` — the 11 code scorers below that need only tool *names* / status / input-variables / output
  text (no captured arguments).
- `TOOL_ARGUMENT_SCORERS` — 3 opt-in code scorers that also inspect tool-call *arguments*; only meaningful when content
  capture is on (they self-skip with
  `Feedback(None)` otherwise). Regression includes them by default; both eval workers
  use `DETERMINISTIC_SCORERS`.
- `ALL_DETERMINISTIC_SCORERS` = `DETERMINISTIC_SCORERS` + `TOOL_ARGUMENT_SCORERS`.

**Consumers:** **R** = `regression` (live agent) · **W** = `eval-service-worker`
(blocking guardrail, per-run) · **A** = `eval-async-worker` (non-blocking, per-run). See each
service's README for exactly how it sources the scorer inputs.

| Scorer                                                | Type      | Bundle        | What it checks                                                                    | Consumers |
|-------------------------------------------------------|-----------|---------------|-----------------------------------------------------------------------------------|-----------|
| `no_tool_errors`                                      | Code      | DETERMINISTIC | No tool call ended in an error/failed status                                      | R · W · A |
| `final_recommendation_format`                        | Code      | DETERMINISTIC | Final line is exactly APPROVE or REJECT, separate from semantic evidence judging | R · W · A |
| `tool_correctness`                                    | Code      | DETERMINISTIC | Agent calls all expected tools and no inappropriate ones                          | R · W · A |
| `cites_key_evidence_terms`                            | Code      | DETERMINISTIC | Output mentions credit, fraud and affordability evidence                         | R · W · A |
| `risk_checks_precede_affordability`                   | Code      | DETERMINISTIC | Credit and fraud checks precede affordability                                    | R · W · A |
| `no_duplicate_tool_calls`                            | Code      | DETERMINISTIC | No tool is called successfully more than once                                    | R · W · A |
| `no_collateral_check_when_no_collateral`              | Code      | DETERMINISTIC | Value Collateral is not called when `hasCollateral=false`                         | R · W · A |
| `no_bank_statement_for_employed_applicant`            | Code      | DETERMINISTIC | Bank statements are not analysed for EMPLOYED applicants                          | R · W · A |
| `no_verify_employment_for_self_employed_applicant`    | Code      | DETERMINISTIC | Employment is not verified for non-EMPLOYED applicants                            | R · W · A |
| `step_efficiency`                                     | Code      | DETERMINISTIC | At most four total LLM calls including the final answer (+1 for collateral)       | R · W · A |
| `affordability_called_after_income_confirmed`         | Code      | DETERMINISTIC | Affordability is assessed only after income has been confirmed                    | R · W · A |
| `tool_argument_correctness`                           | Code      | TOOL_ARGUMENT | Each expected tool receives the arguments the BPMN wires up for it                | R         |
| `collateral_valuation_called_correctly_when_required` | Code      | TOOL_ARGUMENT | Value Collateral **is** called, with the correct `applicationId`, when required   | R         |
| `requested_amount_passed_to_affordability`            | Code      | TOOL_ARGUMENT | Affordability tool receives the correct `customerId` and `requestedAmount`        | R         |
| `decision_quality`                                    | LLM judge | —             | Final output is a clear, justified APPROVE/REJECT recommendation                  | R · W · A |
| `evidence_citation`                                   | LLM judge | —             | Output grounds its reasoning in the applicant/tool evidence (graded 0–1)          | R · A     |
| `matches_golden`                                      | LLM judge | —             | Output reaches the same decision as the matching golden (needs `expected_output`) | R         |

Notes:

- `matches_golden` requires a golden `expected_output` (an `expectations`
  value), so only the **regression** suite runs it — a bare trace doesn't carry
  it, so `W`/`A` cannot.
- `evidence_citation` treats the Fluxnova-only `agent_goal` as *optional*
  context, so it can run in `A` without it.
- Local demo judging uses OpenAI `gpt-4.1-mini` for decision quality and `gpt-4o-mini`
  for golden matching/evidence citation; select Ollama with the shared
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

The local stack keeps it **off** too: exported traces carry metrics and span structure only. Nothing in the
evaluation path needs it, because both eval workers read their scorer inputs from the agent's process variables (see
[Where eval data lives](#where-eval-data-lives)). For local debugging, set `FLUXNOVA_CAPTURE_GENAI_CONTENT=true` in
`local-dev/.env` and recreate the `fluxnova` pod (`local-dev/default.yml` reads it into the property above).

## Where eval data lives

| Data | Where it is stored | Who can read it (local stack) |
|------|--------------------|-------------------------------|
| Applicant inputs, the agent's conversation (prompts, responses, tool arguments and results), loop count | Fluxnova process variables (`agent:context` variables, `_agentConversationHistory`, `_agentLoopIndex`) in the Fluxnova Postgres database, including history tables kept for the process's `historyTimeToLive` | Fluxnova REST API, Cockpit and Tasklist users (`demo`/`demo` locally), and both eval workers |
| Trace structure: spans, timings, token counts, tool names and status | MLflow trace store (via the OTel Collector) | Anyone who can reach MLflow (no auth locally) |
| Prompt/response content on traces | Not exported unless `FLUXNOVA_CAPTURE_GENAI_CONTENT=true` | as above when enabled |
| Eval results: per-scorer values and rationales, pass/fail | MLflow assessments on the run's trace, one MLflow Evaluation Run per scoring, and (guardrail) `evalPassed`/`evalRationale` process variables | MLflow users; Fluxnova users for the process variables |
| Guardrail dataset record | MLflow evaluation dataset: process instance id, decision keyword (`APPROVE`/`REJECT`), scorer values and rationales; no applicant inputs or full response | MLflow users |
| Regression results | MLflow regression runs and reports (golden inputs are synthetic) | MLflow users |

**How the workers score:** `fluxnova_mlflow_dataset.load_agent_run` reads the agent instance's variables and its
deployed BPMN (for tool display names and the `agent:context` list) over the Fluxnova REST API, and builds the scorer
`inputs`/`outputs`. The run's MLflow trace is looked up only as the anchor for results: passing it to
`mlflow.genai.evaluate` attaches the feedback to it without copying the inputs or outputs into MLflow.

**Things to be aware of:**

- LLM judge rationales are free text and can quote parts of the agent's response or applicant data.
- The judges send the agent's output and inputs to the configured judge provider (OpenAI by default), the same
  provider the agent itself uses.
- The local stack has no access control on MLflow and uses default Fluxnova credentials; see the security notes
  before using it with real data.

## First time setup

Use **macOS Terminal**, **Windows Git Bash**, or a Linux shell. Commands use forward
slashes on every OS. Install Python 3.11+ and [Podman](https://podman.io/docs/installation)
with a running VM on macOS/Windows. Apple Silicon also needs x86 execution support
for the current AMD64-only Fluxnova image; see [platform setup](local-dev/README.md#platform-setup).

From the repository root:

```bash
./setup.sh                         # installs all five packages editable, with dev dependencies
source .venv/bin/activate           # macOS/Linux
# source .venv/Scripts/activate     # Windows Git Bash
cp local-dev/.env.example local-dev/.env  # first time only
```

Set `OPENAI_API_KEY` in `local-dev/.env`. The default demo uses OpenAI for the
agent and judges; Ollama is optional. Startup pulls the configured public images.
Choose a specific interpreter with `PYTHON=python3.11 ./setup.sh` if needed.

```bash
./local-dev/pods-up.sh postgres mlflow fluxnova
./local-dev/pods-up.sh eval-service eval-async observability
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
The run's trace is persisted in MLflow. Workflows with Eval service tasks are scored by eval-service-worker / eval-async-worker (if running).
```

Running `loan-assesment.bpmn` on its own isn't scored automatically: the eval workers are triggered by the Eval service
tasks in `LoanApprovalProcess_AI.bpmn` (below).

Other flags:

```bash
fluxnova-run --skip-deploy fluxnova-runner/config/loan-assesment.yml   # BPMN already deployed
fluxnova-run fluxnova-runner/config/loan-assesment.yml                 # no mock workers (needs real service-task workers/backends)
```

### Running the loan approval workflow (`fluxnova-runner/config/loan_approval_process_ai.yml`)

`bpmn/LoanApprovalProcess_AI.bpmn` (`LoanApprovalProcess_AI`) is the current end-to-end workflow, and the one the UI's
Workflow run tab starts. It invokes the loan-assessment agent as a **Call Activity** (`AgentTask_CreditRisk`,
`calledElement="loanAssessmentProcess"`). Because the called process lives in a separate file, both BPMNs must be
deployed together, so the config lists the extra file under `additional_bpmn_paths`:

```yaml
bpmn_path: bpmn/LoanApprovalProcess_AI.bpmn
additional_bpmn_paths:
  - bpmn/loan-assesment.bpmn        # the called loanAssessmentProcess
```

After the agent, `Gateway_ForkAsyncEval` forks the process into two branches that never rejoin:

- **Guardrail branch:** `Gateway_SkipEvalServiceWorker` → `ServiceTask_EvaluateAgentOutput` (topic `agent-output-eval`,
  **eval-service-worker**) → a failed eval goes to the `Human: Risk Assessment Review` user task → the rest of the loan
  process. Setting the `skipEvalServiceWorker` variable to `true` bypasses the guardrail.
- **Async branch:** `ServiceTask_AsyncEvaluateAgentOutput` (topic `agent-output-eval-async`, **eval-async-worker**) →
  `EndEvent_AsyncEvalRecorded`. It scores and records every run without setting any variables.

The process continues after the agent into tasks mock workers can't complete (user tasks), so the config sets
`wait_for_activity: AgentTask_CreditRisk` and the runner returns as soon as the agent Call Activity completes. The
`--wait-for-activity ACTIVITY_ID` CLI flag overrides this for a single run.

In another activated terminal with `.env` exported, keep mock workers running:

```bash
fluxnova-run-mock-workers fluxnova-runner/config/loan_approval_process_ai.yml
```

In the original terminal:

```bash
fluxnova-run fluxnova-runner/config/loan_approval_process_ai.yml
```

Both Eval tasks are real jobs, not mocked, so start the `eval-service` and `eval-async` pods first (see
`local-dev/README.md`). Without them, the run waits at the guardrail and the async task. Keep the separate mock workers
alive until the run finishes, then stop them with Ctrl+C. The [demo walkthrough](local-dev/README.md#demo-walkthrough)
describes the expected traces, assessments, human-review tasks and dashboards.

> `bpmn/loan-assesment-eval.bpmn` and `fluxnova-runner/config/loan-assesment-eval.yml` are the older eval workflow. It
> only has the blocking guardrail task, so the eval-async-worker never scores its runs.

## Evaluating agent runs

There are three complementary paths, all using the **shared scorers/judges** in `fluxnova_mlflow_dataset.scorers` so
they never disagree on what "good" means:

- **`eval-async-worker`** (non-blocking BPMN external-task worker) — handles `ServiceTask_AsyncEvaluateAgentOutput` on
  its own branch of `LoanApprovalProcess_AI.bpmn`. Scores every run (or a live-adjustable sampled fraction) with
  deterministic checks plus `decision_quality` and `evidence_citation`, logs `Feedback` onto the run's trace, and
  completes the task without routing the process. Best for continuous production scoring. See
  [`eval-async-worker/README.md`](eval-async-worker/README.md).
- **`eval-service-worker`** (blocking BPMN external-task worker) — handles the guardrail task
  `ServiceTask_EvaluateAgentOutput`. Scores that one run with the deterministic scorers **plus** the `decision_quality`
  LLM judge (direct OpenAI in the default demo; optionally via an AI Gateway) and returns `evalPassed`/`evalRationale`,
  which route failed runs to human review. Best for guardrails wired into the workflow. See
  [`eval-service-worker/README.md`](eval-service-worker/README.md).
- **`regression/`** (pytest gating suite) — drives the live agent once per parametrized golden scenario
  and asserts its real output satisfies the shared `decision_quality` and `matches_golden` judges, the
  `evidence_citation` judge, and the full `ALL_DETERMINISTIC_SCORERS` bundle. Best as a CI gate against behavioural
  regressions. See [`regression/README.md`](regression/README.md).

Both workers read their scorer inputs from the agent run's process variables, not from trace content (see
[Where eval data lives](#where-eval-data-lives)). All three write their results to the same PostgreSQL-backed MLflow
tracking store (`postgres-local` pod's `mlflow`
database — see `local-dev/services/postgres-up.sh`).

### Automatic (online) evaluation: `mlflow-judges`

For **online** evaluation — where the MLflow server itself scores a sampled fraction of new traces with no code running
continuously — use the `mlflow-judges` CLI (from `fluxnova-mlflow-dataset`) to register/start/stop the automatic judges.
See [
`fluxnova-mlflow-dataset/README.md`](fluxnova-mlflow-dataset/README.md#mlflow-judges-toggling-automatic-online-evaluation)
and `local-dev/README.md`'s AI-Gateway section for the one-off endpoint setup this depends on.

To view the results in the browser, use the same MLflow tracking server described in "Running the MLflow tracking
server" below (or, if you only need read-only browsing and aren't ingesting new traces, the lighter-weight
`mlflow ui --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --port 5001` works too).

Then open [http://localhost:5001](http://localhost:5001) (or your configured port) and open the experiment named by
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
python -m mlflow server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --serve-artifacts --artifacts-destination local-dev/.mlflow/artifacts --default-artifact-root mlflow-artifacts:/ --host 0.0.0.0 --port 5001
```

This single server also serves the browsable UI at [http://localhost:5001](http://localhost:5001), so once it's running
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
    server --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow --serve-artifacts --artifacts-destination local-dev/.mlflow/artifacts --default-artifact-root mlflow-artifacts:/ --host 0.0.0.0 --port 5001
   ```
5. **Working directory:** `<repo root>`
6. **Python interpreter:** the repo-root `.venv` interpreter (add it via **Add Interpreter → Existing** if not already
   registered).
7. Apply, then run this configuration before starting the OTel Collector or running `fluxnova-run` — leave it running in
   the background for the duration of your session.

## Local development with Podman (Fluxnova + OTel Collector + MLflow + PostgreSQL)

See [`local-dev/README.md`](local-dev/README.md) for the full details on running PostgreSQL, the Fluxnova engine, the
OTel Collector, MLflow, and both eval workers as Podman pods for local development — including troubleshooting
notes and the MLflow AI Gateway judge-endpoint setup.

Use its [platform setup](local-dev/README.md#platform-setup),
[demo walkthrough](local-dev/README.md#demo-walkthrough) and
[troubleshooting](local-dev/README.md#troubleshooting) sections, followed by the
[regression validation sequence](regression/README.md#validation-sequence).

## Config file

Runner deployment, process variables and mock workers are configured in workflow YAML.
The eval-service-worker uses CLI/environment settings, and the eval-async-worker has
its own YAML plus CLI/environment overrides; see their package READMEs.

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
| Judge models         | OpenAI / gpt-4.1-mini (decision quality), gpt-4o-mini (golden matching/evidence); optional Ollama / gemma4:e2b and AI Gateway |
