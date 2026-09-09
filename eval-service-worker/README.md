# eval-service-worker

A standalone BPMN external-task worker that scores a just-completed agentic subprocess run against the
`decision_quality` MLflow judge plus a set of trace-only deterministic scorers, reading data purely from MLflow's
trace store — no BPMN parsing, no Fluxnova REST history calls. See `EVAL-SERVICE-WORKER-PLAN.md` at the repo root for
the full background/scope and `local-dev/README.md`'s "eval-service-worker" section for how to run it as a Podman pod.

**Scorers run per task:**
- `decision_quality` — the nondeterministic `Guidelines` LLM judge.
- `required_tools_called`, `no_tool_errors`, `definitive_decision_stated` — deterministic, trace-only checks (see
  `fluxnova_mlflow_dataset.scorers`).

All four scorers gate the BPMN outcome: `evalPassed` is `True` only when the `decision_quality` judge *and* every
deterministic scorer pass. All four scorers' `Feedback` are logged back onto the same real trace as MLflow assessments,
grouped under one MLflow Evaluation Run (via `mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])`), plus a
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

```bash
pip install -e ../fluxnova-mlflow-dataset   # shared trace-reader + judge definition
pip install -e .
```

## Config

Deliberately **no config file** — this worker is meant to be a slim, independently deployable service, so depending on
another service's YAML (e.g. `fluxnova-runner/config/loan-assesment.yml`) would recreate the exact coupling this worker avoids
everywhere else. Instead, every setting has a hardcoded default in `src/eval_service_worker/config.py`, overridable via
either a CLI flag or an `EVAL_SERVICE_<NAME>` environment variable:

| Setting             | CLI flag             | Env var                         | Default                              |
|---------------------|----------------------|---------------------------------|--------------------------------------|
| Fluxnova REST URL   | `--fluxnova-url`     | `EVAL_SERVICE_FLUXNOVA_URL`     | `http://localhost:8080/engine-rest`  |
| MLflow experiment   | `--experiment-name`  | `EVAL_SERVICE_EXPERIMENT_NAME`  | `fluxnova-loanAssessmentEvalProcess` |
| Process key (tags)  | `--process-key`      | `EVAL_SERVICE_PROCESS_KEY`      | `loanAssessmentEvalProcess`          |
| External-task topic | `--topic`            | `EVAL_SERVICE_TOPIC`            | `agent-output-eval`                  |
| Judge model URI     | `--judge-model`      | `EVAL_SERVICE_JUDGE_MODEL`      | `gateway:/fluxnova-judge`            |
| Lock duration (ms)  | `--lock-duration-ms` | `EVAL_SERVICE_LOCK_DURATION_MS` | `600000` (judge calls can take 90s+, and much longer on CPU-only boxes) |
| MLflow tracking URI | `--tracking-uri`     | `EVAL_SERVICE_TRACKING_URI`     | `http://localhost:5000`              |
| Trace poll timeout (s) | `--trace-poll-timeout` | `EVAL_SERVICE_TRACE_POLL_TIMEOUT` | `30.0` (the collector delivers traces to MLflow asynchronously, so this retries the lookup) |
| Trace poll interval (s) | `--trace-poll-interval` | `EVAL_SERVICE_TRACE_POLL_INTERVAL` | `3.0` |

A CLI flag always wins over the matching env var, which always wins over the default.

> **Experiment alignment (important):** the OTel collector routes **every** trace — from the parent eval process *and*
> the called agent child process — to the single MLflow experiment named by `MLFLOW_EXPERIMENT_ID` (a static collector
> header), regardless of process key. The worker must therefore read from that **same** experiment, so
> `EVAL_SERVICE_EXPERIMENT_NAME` has to name whatever experiment `MLFLOW_EXPERIMENT_ID` points at. `local-dev/` keeps
> both in `local-dev/.env` so they stay in sync (currently `fluxnova-loanAssessmentEvalProcess`). See
> `local-dev/README.md`.

## Run as a worker (host)

```bash
eval-service-worker
# or, pointed at a non-default engine/MLflow server:
eval-service-worker --fluxnova-url http://fluxnova-local:8080/engine-rest --tracking-uri http://mlflow-local:5000
```

Subscribes to the configured topic against the configured `fluxnova_url`, and blocks until interrupted (Ctrl+C).
Requires `FLUXNOVA_USERNAME`/`FLUXNOVA_PASSWORD` env vars only if the engine has auth enabled.

## Score a single completed run manually (no BPMN task needed)

Useful for one-off re-scoring, or for testing without waiting on a live BPMN run:

```python
from eval_service_worker.scoring import score_process_instance

outcome = score_process_instance(
    "<processInstanceId>",
    tracking_uri="http://localhost:5000",
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
