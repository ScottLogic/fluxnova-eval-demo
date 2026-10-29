# eval-service-worker

A standalone BPMN external-task worker that scores a just-completed agentic subprocess run against the
`decision_quality` MLflow judge plus a set of trace-only deterministic scorers, reading data purely from MLflow's
trace store, without BPMN parsing or using process variables as scorer inputs.
The Fluxnova history API is used only to resolve a Call Activity's child instance
before reading its trace. See the [local demo walkthrough](../local-dev/README.md#demo-walkthrough)
for container startup and expected results.

**Scorers run per task:** `decision_quality` (the non-deterministic `Guidelines` LLM judge) plus the full
`DETERMINISTIC_SCORERS` bundle — the trace-only code checks from `fluxnova_mlflow_dataset.scorers`
(`tool_correctness`, `no_tool_errors`, `cites_key_evidence_terms`,
`no_duplicate_tool_calls`, `risk_checks_precede_affordability`, `no_collateral_check_when_no_collateral`, `no_bank_statement_for_employed_applicant`,
`no_verify_employment_for_self_employed_applicant`, `step_efficiency`, `affordability_called_after_income_confirmed`,
`final_recommendation_format`). The final-format check is independent of semantic judging:
the updated agent must put a plain `APPROVE` or `REJECT` on its final line.
This is the deliberately narrow online set: `decision_quality` is the per-run judge
(direct OpenAI in the local demo, or an explicitly configured gateway), and the deterministic checks are effectively free. The heavier judges (`evidence_citation`,
`matches_golden`) are left to the offline `eval-trace-listener` / `regression` suites.

**How the scorer inputs are sourced.** All scorers are decoupled from tracing, so the worker builds their plain-value
inputs *from the trace itself* and passes them in explicitly:

- `trace` — the completed run's MLflow trace (resolved for the child instance, see below), so MLflow links every
  `Feedback` back to it.
- `inputs` — `scorer_inputs_from_trace(trace)` (from `fluxnova_mlflow_dataset`), which derives
  `{input_variables, tool_calls, iterations}` from the `invoke_agent` span so the deterministic scorers can inspect
  tool names/status without any BPMN parsing or REST history call.
- `outputs` — the agent's final answer extracted from the trace's output spans.

All scorers gate the BPMN outcome: `evalPassed` is `True` only when the `decision_quality` judge *and* every
deterministic scorer pass. Every scorer's `Feedback` is logged back onto the same real trace as MLflow assessments,
grouped under one MLflow Evaluation Run (via
`mlflow.genai.evaluate(data=[{"trace": trace, "inputs": ..., "outputs": ...}], scorers=[...])`), plus a
lightweight MLflow evaluation-dataset record. The task completes with `evalPassed` (Boolean, driven by all scorers) /
`evalRationale` (String) output variables, which `loan-assesment-eval.bpmn`'s `ExclusiveGateway_EvalPassed` uses to
route the flow: on pass → `ServiceTask_GenerateReport` → `Gateway_AssessmentDecision` (approve/reject) with a human
`UserTask_ApprovalReview`; on fail → `UserTask_ReviewFailedEval`. Confirmed working end-to-end against a live process
instance.

**Correlating the agent run (Call Activity):** the eval process invokes the loan-assessment agent as a **Call Activity**
(`CallActivity_LoanAssessmentAgent` → `loanAssessmentProcess`), so the agent — and therefore its trace — runs in a
*child* process instance, while `ServiceTask_EvaluateAgentOutput` fires in the *parent*. The worker resolves the child
instance for the parent it's handed (via Fluxnova's history API,
`FluxnovaClient.get_child_instance_id`) and scores the child's trace, falling back to the parent instance id when there
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
from eval_service_worker.scoring import score_process_instance

outcome = score_process_instance(
    "<processInstanceId>",
    tracking_uri="http://localhost:5001",
    process_key="loanAssessmentEvalProcess",
    experiment_name="fluxnova-loanAssessmentEvalProcess",
    judge_model="gateway:/fluxnova-judge",
)
print(outcome.eval_passed, outcome.eval_rationale)
```

## Tests

```bash
pytest tests
```
