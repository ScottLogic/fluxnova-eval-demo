# eval-trace-listener

A slim, independently-deployable service that **tails an MLflow experiment's trace
store** and scores each newly-completed agent run once with the shared trace-only
scorers — the deterministic code checks plus the `decision_quality` and
`evidence_citation` LLM judges. It's an always-on, event-adjacent
way to score runs as they land, with no code needing to run on demand.

## What it does

Every `poll_interval_s` seconds it asks MLflow for the most recent traces in the
configured experiment and, for each one:

1. reads the run's agent name off its `invoke_agent` span (`gen_ai.agent.name`);
2. skips it unless that agent is one of the configured `agent_names` (the
   trace-only "which BPMN agents we care about" filter);
3. skips it unless the run is **complete** — MLflow surfaces a *live* trace (its
   root `invoke_agent` span present) while the subprocess is still running, so
   completion is read off the trace's own terminal state: it's scored only once
   `trace.info.state` is `OK` (a failed `ERROR` run has no valid output to score);
4. skips it if we've **already scored** it (in-memory set for this process, plus a
   check for our own scorer assessments already on the trace so a restart doesn't
   re-score history);
5. otherwise runs the `LISTENER_SCORERS` bundle against the run's extracted
   values (`scorer_inputs_from_trace(trace)`) via
   `mlflow.genai.evaluate(data=[{"trace": trace, "inputs": ..., "outputs": ...}], ...)`, which logs each
   scorer's `Feedback` back onto that same real trace as an assessment and groups
   them under one MLflow **Evaluation Run**.

## Scorers and how the data is retrieved

The listener runs `LISTENER_SCORERS` (defined in `eval_trace_listener.scoring`) — the full
`fluxnova_mlflow_dataset.DETERMINISTIC_SCORERS` bundle **plus** two LLM judges:

- `decision_quality` — the `Guidelines` judge (definitive, evidence-backed APPROVE/REJECT).
- `evidence_citation` — grades how well the output grounds its reasoning in the applicant/tool evidence (0.0–1.0).
- all 10 deterministic code scorers (`required_tools_called`, `no_tool_errors`, `definitive_decision_stated`,
  `tool_correctness`, `all_tool_calls_completed`, the collateral/employment guards, `step_efficiency`,
  `affordability_called_after_income_confirmed`).

**`matches_golden` is deliberately excluded** — it needs a golden `expected_output`, which a bare trace doesn't carry.
That judge stays in the `regression` suite, which has the golden dataset. `agent_goal` (a Fluxnova-only field, not on
the trace) is likewise unavailable here, so `evidence_citation` treats it as optional context.

**How the scorer inputs are sourced.** Every scorer is decoupled from tracing; the listener builds their plain-value
inputs entirely *from the trace it just read*:

- `trace` — the completed run's MLflow trace, so MLflow links every `Feedback` back to it.
- `inputs` — `scorer_inputs_from_trace(trace)` → `{input_variables, tool_calls, iterations}` off the `invoke_agent`
  span (no BPMN parsing, no Fluxnova REST call).
- `outputs` — the agent's final answer extracted from the trace's output spans.

> **Operational note:** the listener uses the shared judge provider (OpenAI by
> default, Ollama when `LLM_JUDGE_PROVIDER=ollama`). Local startup passes the API key,
> provider and container Ollama URL explicitly. See [local-dev](../local-dev/README.md).

## Why poll MLflow instead of receiving OTLP?

The OTel Collector already exports every agent trace straight to MLflow's native
trace store, and `mlflow.search_traces` reads them back **fully assembled** — as the
exact `Trace` object the scorers already consume. Standing up our own OTLP receiver (the `fluxnova_listener` layer this
repo deliberately removed) would mean
reassembling spans by trace-id by hand, translating OTLP's span shape into MLflow's, **and** still reading the trace
back from MLflow to attach assessments to it. Push
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

| Key                   | Default                                 | Purpose                                                                |
|-----------------------|-----------------------------------------|------------------------------------------------------------------------|
| `tracking_uri`        | `http://localhost:5001`                 | MLflow tracking server (HTTP, not `postgresql://`)                     |
| `experiment_name`     | `fluxnova-loanAssessmentEvalProcess`    | Experiment to tail (local startup initializes the collector with this experiment's real ID) |
| `agent_names`         | `[AdHocSubProcess_LoanAssessmentAgent]` | Agents to score; empty ⇒ score every agent                             |
| `poll_interval_s`     | `10`                                    | Seconds between polls                                                  |
| `max_traces_per_poll` | `200`                                   | Upper bound on recent traces pulled per poll                           |

Any setting can be overridden per-environment by an `EVAL_LISTENER_<NAME>` env var or
a CLI flag (flag > env > file > default). See `eval_trace_listener/config.py` and
`main.py`.

## Running

```bash
# Locally (against a host MLflow at :5001)
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
