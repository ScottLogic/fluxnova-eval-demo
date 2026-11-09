# eval-service-worker

The blocking **guardrail** worker: a standalone BPMN external-task worker (topic `agent-output-eval`) that scores a just-completed agentic subprocess run against the
`decision_quality` MLflow judge plus the deterministic scorers. Scorer inputs come from the agent run's process
variables over the Fluxnova REST API, so it needs no prompt/response content on traces. See the [local demo walkthrough](../local-dev/README.md#demo-walkthrough)
for container startup and expected results.

**Scorers run per task:** `decision_quality` (the non-deterministic `Guidelines` LLM judge) plus the full
`DETERMINISTIC_SCORERS` bundle — the code checks from `fluxnova_mlflow_dataset.scorers`
(`tool_correctness`, `no_tool_errors`, `cites_key_evidence_terms`,
`no_duplicate_tool_calls`, `risk_checks_precede_affordability`, `no_collateral_check_when_no_collateral`, `no_bank_statement_for_employed_applicant`,
`no_verify_employment_for_self_employed_applicant`, `step_efficiency`, `affordability_called_after_income_confirmed`,
`final_recommendation_format`). The final-format check is independent of semantic judging:
the updated agent must put a plain `APPROVE` or `REJECT` on its final line.
This is the deliberately narrow online set: `decision_quality` is the per-run judge
(direct OpenAI in the local demo, or an explicitly configured gateway), and the deterministic checks are effectively free. The heavier judges (`evidence_citation`,
`matches_golden`) are left to the non-blocking `eval-async-worker` and the `regression` suite.

**Guardrail vs non-blocking Eval.** In `LoanApprovalProcess_AI.bpmn` the process forks after the agent. This worker
serves the guardrail branch's `ServiceTask_EvaluateAgentOutput`, whose result routes the process. The other branch's
`ServiceTask_AsyncEvaluateAgentOutput` (topic `agent-output-eval-async`) is served by
[`eval-async-worker`](../eval-async-worker/README.md), which scores every run without routing it.

**How the scorer inputs are sourced.** `fluxnova_mlflow_dataset.load_agent_run` reads the agent instance (resolved
for the Call Activity child, see below) from Fluxnova:

- `inputs` — `{input_variables, tool_calls, iterations}`: the `agent:context` variables declared in the deployed BPMN,
  every tool call (display name, status, arguments) from `_agentConversationHistory`, and `_agentLoopIndex`.
- `outputs` — the agent's final answer: the last assistant turn in `_agentConversationHistory`.
- `trace` — the run's MLflow trace, looked up only so MLflow attaches every `Feedback` to it. Passing it with the
  inputs/outputs doesn't copy them into MLflow, so the trace stays content-free.

If the variables can't be read (Fluxnova REST error), the run has no final answer yet, the trace hasn't reached
MLflow yet, or the run number can't be read, the task fails with 3 retries 10 seconds apart. Invalid thresholds or
any other error raise an incident straight away, with no retries.

`evalPassed` is decided by thresholds set on the BPMN task (see [Guardrail thresholds](#guardrail-thresholds)); by
default every applicable scorer, including the `decision_quality` judge, must pass. Every scorer's `Feedback` is logged back onto the same real trace as MLflow assessments,
grouped under one MLflow Evaluation Run (via
`mlflow.genai.evaluate(data=[{"trace": trace, "inputs": ..., "outputs": ...}], scorers=[...])`), plus a
lightweight MLflow evaluation-dataset record. The record is content-free: process instance id, the
`APPROVE`/`REJECT` decision keyword, and each scorer's value and rationale. The task completes with the output
variables listed under [Guardrail thresholds](#guardrail-thresholds); `evalPassed` follows the thresholds.
`LoanApprovalProcess_AI.bpmn` routes on `reviewRequired`; `loan-assesment-eval.bpmn` routes on `evalPassed`:

- `LoanApprovalProcess_AI.bpmn` (current workflow): `Gateway_13tt7bu` ("Further action required?") continues to the
  `Risk Approved?` gateway and the rest of the loan process when `reviewRequired == false`. Anything else (a failed
  eval or a forced every-Nth review) goes to `UserTask_ReviewFailedEval`, where a
  reviewer approves, amends or rejects the agent's decision in Tasklist (see the root README). The task is
  skipped entirely when the `skipEvalServiceWorker` variable is `true`.
- `loan-assesment-eval.bpmn` (older eval workflow): `ExclusiveGateway_EvalPassed` sends a pass to
  `ServiceTask_GenerateReport` → `Gateway_AssessmentDecision` with a human `UserTask_ApprovalReview`, and a fail to
  `UserTask_ReviewFailedEval`.

**Correlating the agent run (Call Activity):** both workflows invoke the loan-assessment agent as a **Call Activity**
(`AgentTask_CreditRisk` or `CallActivity_LoanAssessmentAgent` → `loanAssessmentProcess`), so the agent — and therefore its trace — runs in a
*child* process instance, while `ServiceTask_EvaluateAgentOutput` fires in the *parent*. The worker resolves the child
instance for the parent it's handed (via Fluxnova's history API,
`FluxnovaClient.get_child_instance_id`), reads the child's process variables and attaches results to the child's
trace, falling back to the parent instance id when there
is no child (e.g. running `loan-assesment.bpmn` standalone).

## Install (editable, into the shared repo venv or your own)

For the complete shared environment run `./setup.sh` from the repository root.
The [local development guide](../local-dev/README.md) covers host debugging and
cross-platform container startup. Its `.env` configures a direct OpenAI judge by
default, matching the standalone package's calibrated direct-OpenAI model.

```bash
pip install -e ../fluxnova-mlflow-dataset   # shared trace-reader + judge definition
pip install -e .
```

## Guardrail thresholds

The pass/fail thresholds live in the BPMN, not in this worker, so they can be changed in the Modeler without
redeploying it. They are `camunda:inputParameter`s on the Eval service task (in the Modeler: select the task,
**Inputs**):

```xml
<camunda:inputParameter name="evalMinScore">${execution.hasVariable('evalMinScore') ? evalMinScore : 1.0}</camunda:inputParameter>
<camunda:inputParameter name="evalRequiredScorers">${execution.hasVariable('evalRequiredScorers') ? evalRequiredScorers : 'decision_quality'}</camunda:inputParameter>
```

The value at the end of each expression is the default. A run can override it by starting with a process variable of
the same name; the UI's Workflow run page does this from its "Guardrail thresholds for the next run" controls, and
`fluxnova-run` does it if you add `evalMinScore`/`evalRequiredScorers` to the config's `variables`. A plain literal
(e.g. `1.0`) also works, but then runs can't override it.

| Input                 | Meaning                                                                                       | Default when absent |
|-----------------------|-----------------------------------------------------------------------------------------------|---------------------|
| `evalMinScore`        | Minimum fraction (0–1) of applicable scorers that must pass. `1.0` means every one must pass. | `1.0`               |
| `evalRequiredScorers` | Comma-separated scorer names that must pass whatever the score.                               | none                |

A scorer that gives no verdict (not applicable to this run, e.g. the self-employed check for an employed applicant)
is left out of the score and can't fail the run, even if it's required. `LoanApprovalProcess_AI.bpmn` sets
`1.0` / `decision_quality`, which is the same behaviour as before thresholds existed. `loan-assesment-eval.bpmn` sets
none, so it uses the defaults. Its gateway reads `${evalPassed == true}`, so don't set `evalSampleRate` below 1 for it:
an unsampled run leaves `evalPassed` unset.

The task completes with these process variables:

| Variable            | Type    | Value                                                                         |
|---------------------|---------|-------------------------------------------------------------------------------|
| `evalPassed`        | Boolean | Whether the thresholds were met                                               |
| `evalScore`         | Double  | Fraction of applicable scorers that passed                                    |
| `evalFailedScorers` | String  | Comma-separated applicable scorers that failed, even if the run still passed |
| `evalRationale`     | String  | Why it passed or failed, including the failed scorers' rationales            |
| `evalSampled`       | Boolean | Whether this run was scored (see [Sampling and every-Nth review](#sampling-and-every-nth-review)) |
| `reviewRequired`    | Boolean | Whether the run goes to human review; `LoanApprovalProcess_AI.bpmn` routes on this |
| `reviewReason`      | String  | `FAILED_EVAL` and/or `FORCED_EVERY_N` (comma-separated); empty when no review |
| `runNumber`         | Integer | The run's position among this process's runs; only set when every-Nth review is on |

An unsampled run gets only `evalSampled=false`, `reviewRequired=false` and an empty `reviewReason` (plus `runNumber`
when `forceReviewEveryN > 0`): it isn't scored,
so `evalPassed`/`evalScore` aren't set.

Invalid settings (a non-numeric or out-of-range `evalMinScore` or `evalSampleRate`, a negative or fractional
`forceReviewEveryN`, or an unknown name in `evalRequiredScorers`) fail the task straight away with an incident naming
the problem, before any judge call.

### Sampling and every-Nth review

Two more inputs on the same task decide which runs are scored and which go to a human:

| Input               | Meaning                                                                                                  | Default |
|---------------------|----------------------------------------------------------------------------------------------------------|---------|
| `evalSampleRate`    | Fraction (0–1) of runs the guardrail scores. An unsampled run is completed straight away, without scoring or review, and the loan carries on. | `1.0` (every run) |
| `forceReviewEveryN` | Send every Nth run of the process to human review whatever its score. Such runs are always scored, so the reviewer sees the result. | `0` (off) |

`reviewRequired` is true when a scored run fails (`FAILED_EVAL`) or the run is one of every N (`FORCED_EVERY_N`); both
reasons are recorded when both apply. The run number is the run's position among all runs of the process, counted
from the engine's history (`FluxnovaClient.get_run_number`), so the count survives worker restarts. It counts every
version of the process, and restarts only if that history is removed (e.g. once runs pass the process's
`historyTimeToLive`). `fluxnova-run` (without `--skip-deploy`) deletes earlier deployments with cascade, which removes
their history and restarts this count. The async eval (eval-async-worker) is separate: it has its own sample rate and never routes runs.

## Config

Deliberately **no config file** — this worker is meant to be a slim, independently deployable service, so depending on
another service's YAML (e.g. `fluxnova-runner/config/loan-assesment.yml`) would recreate the exact coupling this worker
avoids
everywhere else. Instead, every setting has a hardcoded default in `src/eval_service_worker/config.py`, overridable via
either a CLI flag or an `EVAL_SERVICE_<NAME>` environment variable:

| Setting                 | CLI flag                | Env var                            | Default                                                                                     |
|-------------------------|-------------------------|------------------------------------|---------------------------------------------------------------------------------------------|
| Fluxnova REST URL       | `--fluxnova-url`        | `EVAL_SERVICE_FLUXNOVA_URL`        | `http://localhost:8080/engine-rest`                                                         |
| MLflow experiment       | `--experiment-name`     | `EVAL_SERVICE_EXPERIMENT_NAME`     | `fluxnova-loanAssessmentEvalProcess`                                                        |
| Process key (tags)      | `--process-key`         | `EVAL_SERVICE_PROCESS_KEY`         | `loanAssessmentEvalProcess`                                                                 |
| External-task topic     | `--topic`               | `EVAL_SERVICE_TOPIC`               | `agent-output-eval`                                                                         |
| Judge model URI         | `--judge-model`         | `EVAL_SERVICE_JUDGE_MODEL`         | `openai:/gpt-4.1-mini` (needs `OPENAI_API_KEY`; no pre-created gateway endpoint) |
| Lock duration (ms)      | `--lock-duration-ms`    | `EVAL_SERVICE_LOCK_DURATION_MS`    | `600000` (judge calls can take 90s+, and much longer on CPU-only boxes)                     |
| MLflow tracking URI     | `--tracking-uri`        | `EVAL_SERVICE_TRACKING_URI`        | `http://localhost:5001`                                                                     |
| Trace poll timeout (s)  | `--trace-poll-timeout`  | `EVAL_SERVICE_TRACE_POLL_TIMEOUT`  | `90.0` (allows asynchronous collector export) |
| Trace poll interval (s) | `--trace-poll-interval` | `EVAL_SERVICE_TRACE_POLL_INTERVAL` | `3.0`                                                                                       |

A CLI flag always wins over the matching env var, which always wins over the default.

> **Experiment alignment:** local MLflow startup creates/resolves
> `EVAL_SERVICE_EXPERIMENT_NAME` and shares its actual numeric ID with the collector.
> All agent traces and both evaluation services use this experiment, regardless of
> process key. No fixed `MLFLOW_EXPERIMENT_ID` is needed.

## Run as a worker (host)

```bash
eval-service-worker
# or, pointed at a non-default engine/MLflow server:
eval-service-worker --fluxnova-url http://fluxnova-local:8080/engine-rest --tracking-uri http://mlflow-local:5000
```

Subscribes to the configured topic against the configured `fluxnova_url`, and blocks until interrupted (Ctrl+C).
Requires `FLUXNOVA_USERNAME`/`FLUXNOVA_PASSWORD` env vars only if the engine has auth enabled.

Idle fetch long polling is capped at ten seconds, independently of the ten-minute
task lease used for judging. A stopped worker's existing lease can still remain;
use the [controlled review-route check](../local-dev/README.md#controlled-human-review-routing)
for a targeted validation handoff instead of trying to lock an already-owned task.

## Score a single completed run manually (no BPMN task needed)

Useful for one-off re-scoring, or for testing without waiting on a live BPMN run:

```python
from fluxnova_mlflow_dataset import FluxnovaClient
from eval_service_worker.scoring import score_process_instance

outcome = score_process_instance(
    "<agent (child) processInstanceId>",
    client=FluxnovaClient("http://localhost:8080/engine-rest"),
    tracking_uri="http://localhost:5001",
    process_key="loanAssessmentEvalProcess",
    experiment_name="fluxnova-loanAssessmentEvalProcess",
    judge_model="openai:/gpt-4.1-mini",
)
print(outcome.eval_passed, outcome.eval_score, outcome.eval_rationale)
```

## Tests

```bash
pytest tests
```
