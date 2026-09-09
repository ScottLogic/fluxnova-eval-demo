# eval-trace-listener

A slim, independently-deployable service that **tails an MLflow experiment's trace
store** and scores each newly-completed agent run once with the shared
**deterministic (trace-only) scorers**. It's an always-on, event-adjacent
alternative to the on-demand `mlflow-eval` batch CLI — and the first step towards
replacing it.

## What it does

Every `poll_interval_s` seconds it asks MLflow for the most recent traces in the
configured experiment and, for each one:

1. reads the run's agent name off its `invoke_agent` span (`gen_ai.agent.name`);
2. skips it unless that agent is one of the configured `agent_names` (the
   trace-only "which BPMN agents we care about" filter);
3. skips it unless the run is **complete** — a run's `invoke_agent` (root) span is
   only exported once the subprocess has ended, so its presence *is* the completion
   signal (the same one `MlflowTraceReader.find_completed_runs` uses);
4. skips it if we've **already scored** it (in-memory set for this process, plus a
   check for our own scorer assessments already on the trace so a restart doesn't
   re-score history);
5. otherwise runs `fluxnova_mlflow_dataset.DETERMINISTIC_SCORERS` against the trace
   via `mlflow.genai.evaluate(data=[{"trace": trace}], ...)`, which logs each
   scorer's `Feedback` back onto that same real trace as an assessment and groups
   them under one MLflow **Evaluation Run**.

Currently just the deterministic scorers run (`required_tools_called`,
`no_tool_errors`, `definitive_decision_stated`) — the non-deterministic
`decision_quality` LLM judge is intentionally out of scope for now.

## Why poll MLflow instead of receiving OTLP?

The OTel Collector already exports every agent trace straight to MLflow's native
trace store, and `mlflow.search_traces` reads them back **fully assembled** — as the
exact `Trace` object the scorers already consume. Standing up our own OTLP receiver
(the `fluxnova_listener` layer this repo deliberately removed) would mean
reassembling spans by trace-id by hand, translating OTLP's span shape into MLflow's,
**and** still reading the trace back from MLflow to attach assessments to it. Push
would only change the *trigger*, not the scoring source or sink — at the cost of an
extra receiver + reassembly + a collector-config change. Polling gives the same
scoring path with far less machinery, at the price of a few seconds' latency.

## Filtering: by agent, not by BPMN process

All traces are routed to a single MLflow experiment, and the agent trace carries no
BPMN process-definition key — the same `loanAssessmentProcess` agent subprocess
produces an identical trace whether it was started standalone or via the eval BPMN's
Call Activity. So the trace-only handle for "the processes we care about" is the
agent name (`gen_ai.agent.name`), configured in `agent_names`. Distinguishing
eval-vs-standalone *invocations* of the same agent isn't possible from the trace
alone (it would need a Fluxnova REST lookup) and is out of scope.

## Configuration

Static settings live in a **YAML config file** (`config.yaml` — the one baked into
the image is a worked example). Every key is optional and falls back to a built-in
default; unknown keys are ignored so the file can carry forward-looking settings.

| Key                   | Default                                | Purpose                                                            |
|-----------------------|----------------------------------------|--------------------------------------------------------------------|
| `tracking_uri`        | `http://localhost:5000`                | MLflow tracking server (HTTP, not `postgresql://`)                 |
| `experiment_name`     | `fluxnova-loanAssessmentEvalProcess`   | Experiment to tail (must match the collector's `MLFLOW_EXPERIMENT_ID`) |
| `agent_names`         | `[AdHocSubProcess_LoanAssessmentAgent]`| Agents to score; empty ⇒ score every agent                         |
| `poll_interval_s`     | `10`                                   | Seconds between polls                                              |
| `max_traces_per_poll` | `200`                                  | Upper bound on recent traces pulled per poll                       |

Any setting can be overridden per-environment by an `EVAL_LISTENER_<NAME>` env var or
a CLI flag (flag > env > file > default). See `eval_trace_listener/config.py` and
`main.py`.

## Running

```bash
# Locally (against a host MLflow at :5000)
eval-trace-listener --config eval-trace-listener/config.yaml

# In Podman (needs mlflow-local running — reaches it by pod name)
cd local-dev/services && ./eval-listener-up.sh     # ./eval-listener-down.sh to stop
# or via compose:  podman compose --profile eval up -d eval-trace-listener-local
```

## Development

```bash
pip install -e "./eval-trace-listener[dev]"
cd eval-trace-listener && python -m pytest -q && python -m ruff check .
```
