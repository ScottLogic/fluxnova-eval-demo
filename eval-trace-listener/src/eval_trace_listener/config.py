"""Configuration for the ``eval-trace-listener`` standalone service.

The service is the worker for the non-blocking Eval service task
(``ServiceTask_AsyncEvaluateAgentOutput`` in ``bpmn/LoanApprovalProcess_AI.bpmn``).
It reads its static settings from a **YAML config file** (see ``config.yaml``).
Every field has a built-in default, and any of them can be overridden
per-environment via CLI flags / ``EVAL_LISTENER_*`` environment variables (see
``main.py``), so container deployments can point at pod-name-based URLs without
editing the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Fluxnova engine REST base URL this worker fetches external tasks from.
DEFAULT_FLUXNOVA_URL = "http://localhost:8080/engine-rest"

# External-task topic of the non-blocking Eval service task.
DEFAULT_TOPIC = "agent-output-eval-async"

# Judge calls can take 90s+ (much longer on CPU-only boxes), so the task lease
# must comfortably exceed a full scoring run or Fluxnova hands the task to
# another worker mid-scoring. Matches eval-service-worker's default.
DEFAULT_LOCK_DURATION_MS = 600_000

# MLflow tracking server the scorers read the agent run's trace from and log
# their assessments back to. Must be an HTTP(S) URL, not a postgresql:// path.
DEFAULT_TRACKING_URI = "http://localhost:5001"

# The experiment the OTel Collector routes every trace into (resolved by
# local-dev/mlflow/bootstrap.py), matching eval-service-worker's default.
DEFAULT_EXPERIMENT_NAME = "fluxnova-loanAssessmentEvalProcess"

# The task usually fires seconds after the agent subprocess ends, before the
# collector has delivered its trace to MLflow, so wait for it before scoring.
DEFAULT_TRACE_POLL_TIMEOUT_S = 90.0
DEFAULT_TRACE_POLL_INTERVAL_S = 3.0

# Fraction of async Eval tasks to actually score: 1.0 scores every run, 0.0
# none. Unsampled tasks are completed straight away without scoring. Can be
# changed live via the control endpoint (control.py).
DEFAULT_SAMPLE_RATE = 1.0

# Host/port the sample-rate control endpoint (control.py) binds on. 0.0.0.0 so
# it's reachable from sibling containers, not just localhost inside this pod.
DEFAULT_CONTROL_HOST = "0.0.0.0"
DEFAULT_CONTROL_PORT = 8092


@dataclass
class ListenerConfig:
    """All settings needed to serve the async Eval topic.

    Construct directly (every field has a default), load from a YAML file with
    :meth:`from_file`, or build from an already-parsed mapping with
    :meth:`from_mapping`. ``main.py`` layers CLI/env overrides on top.
    """

    fluxnova_url: str = DEFAULT_FLUXNOVA_URL
    topic: str = DEFAULT_TOPIC
    lock_duration_ms: int = DEFAULT_LOCK_DURATION_MS
    tracking_uri: str = DEFAULT_TRACKING_URI
    experiment_name: str = DEFAULT_EXPERIMENT_NAME
    trace_poll_timeout_s: float = DEFAULT_TRACE_POLL_TIMEOUT_S
    trace_poll_interval_s: float = DEFAULT_TRACE_POLL_INTERVAL_S
    sample_rate: float = DEFAULT_SAMPLE_RATE
    control_host: str = DEFAULT_CONTROL_HOST
    control_port: int = DEFAULT_CONTROL_PORT

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> ListenerConfig:
        """Build a config from a parsed mapping, filling any absent key from the
        dataclass defaults. Unknown keys are ignored so the file can carry
        forward-looking settings this version doesn't read yet.
        """
        raw = raw or {}
        d = cls()
        return cls(
            fluxnova_url=str(raw.get("fluxnova_url", d.fluxnova_url)).rstrip("/"),
            topic=str(raw.get("topic", d.topic)),
            lock_duration_ms=int(raw.get("lock_duration_ms", d.lock_duration_ms)),
            tracking_uri=str(raw.get("tracking_uri", d.tracking_uri)).rstrip("/"),
            experiment_name=str(raw.get("experiment_name", d.experiment_name)),
            trace_poll_timeout_s=float(raw.get("trace_poll_timeout_s", d.trace_poll_timeout_s)),
            trace_poll_interval_s=float(
                raw.get("trace_poll_interval_s", d.trace_poll_interval_s)
            ),
            sample_rate=float(raw.get("sample_rate", d.sample_rate)),
            control_host=str(raw.get("control_host", d.control_host)),
            control_port=int(raw.get("control_port", d.control_port)),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> ListenerConfig:
        """Load configuration from a YAML file (see ``config.yaml``)."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_mapping(yaml.safe_load(text))
