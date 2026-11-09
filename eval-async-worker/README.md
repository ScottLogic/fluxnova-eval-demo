# eval-async-worker

The external-task worker for the **non-blocking Eval service task** in
`bpmn/LoanApprovalProcess_AI.bpmn`. It scores each agent run with the shared
scorers (the deterministic code checks plus the `decision_quality` and
`evidence_citation` LLM judges) and records the results in MLflow, without ever
holding up or routing the process.

> The name is historical: this service used to poll MLflow's trace store for any
> completed agent run. Scoring is now triggered by the process itself, once per
> run, through a BPMN service task.

## Where it sits in the process

```
AgentTask_CreditRisk ─▶ Gateway_ForkAsyncEval (parallel)
                          ├─▶ skip-eval gateway ─▶ blocking guardrail (eval-service-worker) ─▶ … loan continues
                          └─▶ ServiceTask_AsyncEvaluateAgentOutput (this service) ─▶ EndEvent_AsyncEvalRecorded
```

The two branches never join, so a slow judge or a scoring failure here never delays
the loan decision. The async branch runs even when `skipEvalServiceWorker` is
`true`, because that flag only skips the blocking guardrail.

| Service               | Topic                     | Role                         | Completes with                |
|-----------------------|---------------------------|------------------------------|-------------------------------|
| `eval-service-worker` | `agent-output-eval`       | Blocking guardrail           | `evalPassed`, `evalRationale` |
| `eval-async-worker` | `agent-output-eval-async` | Non-blocking production Eval | no variables                  |

## What it does per task

1. Resolves the agent's process instance. The agent runs in a Call Activity child
   (`loanAssessmentProcess`) and its trace is tagged with the child's id. If there
   is no child, or the lookup fails, it falls back to the parent.
2. Rolls the **sample rate** dice. If the run isn't sampled, it completes the task
   straight away without scoring.
3. Waits for the run's trace to reach MLflow (`trace_poll_timeout_s`). The task
   fires as soon as the agent finishes, which is usually before the OTel Collector
   has delivered the trace.
4. Runs `ASYNC_EVAL_SCORERS` through `mlflow.genai.evaluate`. Each scorer's `Feedback`
   is logged onto that trace as an assessment, grouped under one MLflow
   **Evaluation Run**.
5. Completes the task **with no variables**. The parallel token shares the process
   scope, so writing results here could change how the guardrail branch routes.

**Failures:** if the trace isn't available yet, or MLflow returns no eval results,
the task is failed with 3 retries 10 seconds apart. Any other error fails it with no
retries. Either way the result is an incident on this task only. The loan branch
carries on, but the process instance stays active until the incident is resolved.

## Scorers

`ASYNC_EVAL_SCORERS` (in `eval_async_worker.scoring`) is the full
`fluxnova_mlflow_dataset.DETERMINISTIC_SCORERS` bundle **plus** two LLM judges:

- `decision_quality`: the `Guidelines` judge (definitive, evidence-backed APPROVE/REJECT).
- `evidence_citation`: grades how well the output grounds its reasoning in the applicant and tool evidence (0.0–1.0).

`matches_golden` is excluded because it needs a golden `expected_output`. That judge
stays in the `regression` suite.

Scorer inputs currently come from the trace (`scorer_inputs_from_trace(trace)` and
the final output spans), so gen_ai content capture must stay on for now. Moving
them to process variables is item 2 in `BLOG_ALIGNMENT.md`.

> **Operational note:** the judges use the shared provider (OpenAI by default,
> Ollama when `LLM_JUDGE_PROVIDER=ollama`). Local startup passes the API key,
> provider and container Ollama URL explicitly. See [local-dev](../local-dev/README.md).

## Sample rate

The demo scores every run (`sample_rate: 1.0`), and the UI has no switch for it. To
score a fraction of runs instead, set `sample_rate` in config, or change it live with
`GET`/`PUT /config` on port 8092 (published with `EVAL_ASYNC_CONTROL_PORT`), e.g.
`curl -X PUT localhost:8092/config -d '{"sample_rate": 0.5}'`. Unsampled tasks are
completed without scoring.

## Configuration

Static settings live in a **YAML config file** (`config.yaml`, which is baked into
the image). Every key is optional and falls back to a built-in default, and unknown
keys are ignored.

| Key                     | Default                              | Purpose                                              |
|-------------------------|--------------------------------------|------------------------------------------------------|
| `fluxnova_url`          | `http://localhost:8080/engine-rest`  | Engine REST URL to fetch tasks from                  |
| `topic`                 | `agent-output-eval-async`            | External-task topic                                  |
| `lock_duration_ms`      | `600000`                             | Task lease; must exceed a full scoring run           |
| `tracking_uri`          | `http://localhost:5001`              | MLflow tracking server (HTTP, not `postgresql://`)   |
| `experiment_name`       | `fluxnova-loanAssessmentEvalProcess` | Experiment the collector writes traces into          |
| `trace_poll_timeout_s`  | `90`                                 | Max wait for the run's trace to land                 |
| `trace_poll_interval_s` | `3`                                  | Seconds between trace lookups                        |
| `sample_rate`           | `1.0`                                | Fraction of runs to score                            |
| `control_host`          | `0.0.0.0`                            | Control endpoint bind host                           |
| `control_port`          | `8092`                               | Control endpoint port                                |

Any setting can be overridden by an `EVAL_ASYNC_<NAME>` env var (for example
`EVAL_ASYNC_FLUXNOVA_URL`, `EVAL_ASYNC_TRACE_POLL_TIMEOUT`) or a CLI flag
(flag > env > file > default). `FLUXNOVA_USERNAME`/`FLUXNOVA_PASSWORD` are used for
engine auth when set.

## Running

```bash
# Locally (against a host engine at :8080 and MLflow at :5001)
eval-async-worker --config eval-async-worker/config.yaml

# In Podman (needs fluxnova-local and mlflow-local running)
cd local-dev/services && ./eval-async-up.sh     # ./eval-async-down.sh to stop
# or via compose:  podman compose --profile eval up -d eval-async-worker-local
```

If the eval-async-worker isn't running, async Eval tasks wait in the engine, and process
instances stay active after the loan branch has finished.

## Development

```bash
pip install -e "./eval-async-worker[dev]"
cd eval-async-worker && python -m pytest -q && python -m ruff check .
```
