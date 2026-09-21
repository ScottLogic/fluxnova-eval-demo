"""Which evals are configured to run, for the listener and the service worker.

Reads the actual scorer objects each service runs — not a hand-maintained
duplicate list — so this endpoint can never drift out of sync with what really
executes. Both are pure in-memory objects to construct (no network calls, no
BPMN/Fluxnova access), so this is safe to call on every page load.
"""

from __future__ import annotations

from typing import Any


def _clean_docstring(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(line.strip() for line in doc.strip().splitlines()).strip()


def _describe(scorer: Any) -> dict[str, str]:
    description = getattr(scorer, "description", None)
    if not description:
        original_func = getattr(scorer, "_original_func", None)
        description = _clean_docstring(getattr(original_func, "__doc__", None))
    return {"name": scorer.name, "description": description or ""}


def listener_scorers() -> list[dict[str, str]]:
    """Scorers `eval-trace-listener` runs per (sampled) trace — see its scoring.py."""
    from eval_trace_listener.scoring import LISTENER_SCORERS

    return [_describe(scorer) for scorer in LISTENER_SCORERS]


def service_worker_scorers() -> list[dict[str, str]]:
    """Scorers `eval-service-worker` runs synchronously per BPMN task — see its
    config.py (DEFAULT_JUDGE_MODEL) and scoring.py."""
    from eval_service_worker.config import EvalServiceConfig
    from fluxnova_mlflow_dataset.scorers import DETERMINISTIC_SCORERS, decision_quality_judge

    judge_model = EvalServiceConfig().judge_model
    scorers = [decision_quality_judge(judge_model), *DETERMINISTIC_SCORERS]
    return [_describe(scorer) for scorer in scorers]
