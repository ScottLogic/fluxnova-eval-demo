# eval-service-worker

A standalone BPMN external-task worker that scores a just-completed agentic subprocess run against the
`decision_quality` MLflow judge plus a set of trace-only deterministic scorers, reading data purely from MLflow's
trace store — no BPMN parsing, no Fluxnova REST history calls. See `EVAL-SERVICE-WORKER-PLAN.md` at the repo root for
the full background/scope and `local-dev/README.md`'s "eval-service-worker" section for how to run it as a Podman pod.

**Scorers run per task:**
- `decision_quality` — the nondeterministic `Guidelines` LLM judge (the only one that gates the BPMN outcome).
- `required_tools_called`, `no_tool_errors`, `definitive_decision_stated` — deterministic, trace-only checks (see
  `fluxnova_mlflow_dataset.scorers`), recorded for visibility but not (yet) wired into the gateway condition.

All four scorers' `Feedback` are logged back onto the same real trace as MLflow assessments, grouped under one MLflow
Evaluation Run (via `mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])`), plus a lightweight MLflow
evaluation-dataset record. The task completes with `evalPassed` (Boolean, driven solely by `decision_quality`) /
`evalRationale` (String) output variables, which `loan-assesment-eval.bpmn`'s `ExclusiveGateway_EvalPassed` uses to
route to `EndEvent_EvalPassed`/`EndEvent_EvalFailed` — confirmed working end-to-end against a live process instance.

## Install (editable, into the harness venv or your own)

```bash
pip install -e ../fluxnova-mlflow-dataset   # shared trace-reader + judge definition
pip install -e .
```

## Config

Deliberately **no config file** — this worker is meant to be a slim, independently deployable service, so depending on
another service's YAML (e.g. `harness/config/loan-assesment.yml`) would recreate the exact coupling this worker avoids
everywhere else. Instead, every setting has a hardcoded default in `src/eval_service_worker/config.py`, overridable via
either a CLI flag or an `EVAL_SERVICE_<NAME>` environment variable:

| Setting             | CLI flag             | Env var                         | Default                              |
|---------------------|----------------------|---------------------------------|--------------------------------------|
| Fluxnova REST URL   | `--fluxnova-url`     | `EVAL_SERVICE_FLUXNOVA_URL`     | `http://localhost:8080/engine-rest`  |
| MLflow experiment   | `--experiment-name`  | `EVAL_SERVICE_EXPERIMENT_NAME`  | `fluxnova-loanAssessmentEvalProcess` |
| Process key (tags)  | `--process-key`      | `EVAL_SERVICE_PROCESS_KEY`      | `loanAssessmentEvalProcess`          |
| External-task topic | `--topic`            | `EVAL_SERVICE_TOPIC`            | `agent-output-eval`                  |
| Judge model URI     | `--judge-model`      | `EVAL_SERVICE_JUDGE_MODEL`      | `gateway:/fluxnova-judge`            |
| Lock duration (ms)  | `--lock-duration-ms` | `EVAL_SERVICE_LOCK_DURATION_MS` | `180000` (judge calls can take 90s+) |
| MLflow tracking URI | `--tracking-uri`     | `EVAL_SERVICE_TRACKING_URI`     | `http://localhost:5000`              |
| Trace poll timeout (s) | `--trace-poll-timeout` | `EVAL_SERVICE_TRACE_POLL_TIMEOUT` | `30.0` (the collector delivers traces to MLflow asynchronously, so this retries the lookup) |
| Trace poll interval (s) | `--trace-poll-interval` | `EVAL_SERVICE_TRACE_POLL_INTERVAL` | `3.0` |

A CLI flag always wins over the matching env var, which always wins over the default.

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
