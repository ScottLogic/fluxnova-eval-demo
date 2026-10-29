"""Configuration for the ``eval-trace-listener`` standalone service.

Unlike ``eval-service-worker`` (whose settings are hardcoded defaults in code),
this service reads its *static data* — which MLflow experiment to tail, which
BPMN agents to score, how often to poll — from a **YAML config file** (see
``config.yaml`` in this package for a worked example). That keeps the "what to
evaluate" knobs in one declarative place, ready to grow (thresholds, judge
models, per-agent scorer selection) without code changes.

All fields still have sensible built-in defaults, and any of them can be
overridden per-environment via CLI flags / ``EVAL_LISTENER_*`` environment
variables (see ``main.py``) so container deployments can point at pod-name-based
URLs without editing the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# MLflow tracking server address the OTel Collector exports traces into — must be
# an HTTP(S) URL (not a direct postgresql:// path) so the trace store is queryable
# over the REST API from this service's own pod.
DEFAULT_TRACKING_URI = "http://localhost:5001"

# The MLflow experiment whose traces are tailed. The OTel Collector routes ALL
# traces (parent eval process + the called agent subprocess) to a single
# experiment (resolved by local-dev/mlflow/bootstrap.py) — so this must name that
# experiment, matching eval-service-worker's default (see local-dev/.env's
# EVAL_SERVICE_EXPERIMENT_NAME). The agent runs we score land here tagged with
# their invoke_agent span's gen_ai.agent.name (see agent_names below).
DEFAULT_EXPERIMENT_NAME = "fluxnova-loanAssessmentEvalProcess"

# Only runs whose invoke_agent span's `gen_ai.agent.name` is in this set get
# scored — the trace-only handle for "the BPMN agents we care about" (see the
# README's filtering section). Empty means *score every agent* in the experiment.
DEFAULT_AGENT_NAMES: tuple[str, ...] = ("AdHocSubProcess_LoanAssessmentAgent",)

# How often to re-poll the trace store for newly-completed runs.
DEFAULT_POLL_INTERVAL_S = 10.0

# Upper bound on how many recent traces to pull per poll. Already-scored traces
# are cheaply skipped (see listener dedup), so this only needs to comfortably
# exceed the number of runs that can complete within one poll interval.
DEFAULT_MAX_TRACES_PER_POLL = 200

# Fraction of newly-completed, in-scope traces to actually score — 1.0 scores
# every one (the historical default/behaviour), 0.0 scores none, 0.1 ~1-in-10,
# etc. See control.py for how this can be changed live, without restarting the
# process, via a small always-on HTTP control endpoint.
DEFAULT_SAMPLE_RATE = 1.0

# Host/port the sample-rate control endpoint (control.py) binds on. 0.0.0.0 so
# it's reachable from sibling containers, not just localhost inside this pod.
DEFAULT_CONTROL_HOST = "0.0.0.0"
DEFAULT_CONTROL_PORT = 8092


@dataclass
class ListenerConfig:
    """All settings needed to tail one experiment and score its agents' runs.

    Construct directly (every field has a default), load from a YAML file with
    :meth:`from_file`, or build from an already-parsed mapping with
    :meth:`from_mapping`. ``main.py`` layers CLI/env overrides on top.
    """

    tracking_uri: str = DEFAULT_TRACKING_URI
    experiment_name: str = DEFAULT_EXPERIMENT_NAME
    agent_names: list[str] = field(default_factory=lambda: list(DEFAULT_AGENT_NAMES))
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    max_traces_per_poll: int = DEFAULT_MAX_TRACES_PER_POLL
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
        defaults = cls()
        agent_names = raw.get("agent_names")
        return cls(
            tracking_uri=str(raw.get("tracking_uri", defaults.tracking_uri)).rstrip("/"),
            experiment_name=str(raw.get("experiment_name", defaults.experiment_name)),
            agent_names=list(agent_names) if agent_names is not None else defaults.agent_names,
            poll_interval_s=float(raw.get("poll_interval_s", defaults.poll_interval_s)),
            max_traces_per_poll=int(raw.get("max_traces_per_poll", defaults.max_traces_per_poll)),
            sample_rate=float(raw.get("sample_rate", defaults.sample_rate)),
            control_host=str(raw.get("control_host", defaults.control_host)),
            control_port=int(raw.get("control_port", defaults.control_port)),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> ListenerConfig:
        """Load configuration from a YAML file (see ``config.yaml``)."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_mapping(yaml.safe_load(text))
