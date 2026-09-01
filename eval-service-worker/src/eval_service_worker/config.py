"""Configuration for the ``eval-service-worker`` standalone service.

Deliberately **not** read from ``harness``'s workflow YAML config
(``harness/config/loan-assesment.yml``) — this worker is meant to be a slim,
independently deployable service (its own Podman pod/container), and depending
on another service's config file for its own connection settings would
recreate exactly the coupling that was avoided everywhere else (no BPMN
parsing, no Fluxnova REST calls — see ``EVAL-SERVICE-WORKER-PLAN.md``).

Instead, all settings are simple hardcoded defaults below, overridable via CLI
flags or environment variables (see ``main.py``) — there's only ever one
workflow being scored in this demo, so a config file of its own would just be
one more thing to keep in sync for no real benefit.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fluxnova/Camunda engine REST base URL this worker polls for external tasks.
DEFAULT_FLUXNOVA_URL = "http://localhost:8080/engine-rest"

# The MLflow experiment that scored runs are read from and written back to.
# Matches `fluxnova-<process_key>` for loan-assesment-eval.yml's process_key
# (loanAssessmentEvalProcess) — see fluxnova_mlflow_dataset.store.experiment_name_for.
DEFAULT_EXPERIMENT_NAME = "fluxnova-loanAssessmentEvalProcess"

# Used only to tag dataset records / satisfy the shared write_to_mlflow_dataset()
# helper's (process_key-shaped) signature — naming is always driven by
# DEFAULT_EXPERIMENT_NAME above, not derived from this. Matches the <process id>
# in bpmn/loan-assesment-eval.bpmn (kept distinct from loan-assesment.bpmn's
# "loanAssessmentProcess" so the two BPMNs deploy as separate definitions).
DEFAULT_PROCESS_KEY = "loanAssessmentEvalProcess"

# External-task topic this worker subscribes to.
DEFAULT_TOPIC = "agent-output-eval"

# MLflow judge model URI — gateway-routed, matching the automatic decision_quality
# judge registered via the mlflow-judges CLI (see local-dev/README.md).
DEFAULT_JUDGE_MODEL = "gateway:/fluxnova-judge"

# Judge calls routed through the gateway to a local Ollama model have been
# observed taking 90+ seconds in this environment (see
# EDD-AND-PRODUCTION-EVAL-ANALYSIS.md / EVAL-SERVICE-WORKER-PLAN.md) — the lock
# duration must comfortably exceed that so Fluxnova doesn't reassign the task
# to another worker mid-scoring.
DEFAULT_LOCK_DURATION_MS = 180_000

# MLflow tracking server address — must be an HTTP(S) URL (not a direct
# sqlite:/// path), since gateway-routed judge models are resolved by the
# server process itself.
DEFAULT_TRACKING_URI = "http://localhost:5000"

# How long/often to retry looking up the run's trace in MLflow before giving up.
# The OTel Collector delivers spans asynchronously, so this service task (which
# runs immediately after the subprocess ends) can otherwise beat the trace's
# arrival — see fluxnova_mlflow_dataset.traces.MlflowTraceReader.wait_for_trace.
DEFAULT_TRACE_POLL_TIMEOUT_S = 30.0
DEFAULT_TRACE_POLL_INTERVAL_S = 3.0


@dataclass
class EvalServiceConfig:
    """All settings needed to run the eval-service-worker against one workflow.

    Construct directly (all fields have sensible defaults) and override only
    what differs for your environment — see ``main.py`` for the CLI
    flags/environment variables that do this for the ``eval-service-worker``
    entry point.
    """

    fluxnova_url: str = DEFAULT_FLUXNOVA_URL
    experiment_name: str = DEFAULT_EXPERIMENT_NAME
    process_key: str = DEFAULT_PROCESS_KEY
    topic: str = DEFAULT_TOPIC
    judge_model: str = DEFAULT_JUDGE_MODEL
    lock_duration_ms: int = DEFAULT_LOCK_DURATION_MS
    tracking_uri: str = DEFAULT_TRACKING_URI
    trace_poll_timeout: float = DEFAULT_TRACE_POLL_TIMEOUT_S
    trace_poll_interval: float = DEFAULT_TRACE_POLL_INTERVAL_S
