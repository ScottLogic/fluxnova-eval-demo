"""The complete set of scorers used anywhere in this project, and where.

Reads the actual scorer objects each consumer runs — not a hand-maintained
duplicate list — so this can never drift out of sync with what really
executes. All of these are pure in-memory objects to construct (no network
calls, no BPMN/Fluxnova access), so this is safe to call on every page load.
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


def all_scorers() -> list[dict[str, Any]]:
    """Every scorer this project defines, with where each one runs.

    - **deterministic** — a plain code check (no LLM call), as opposed to an
      LLM-judge scorer (``decision_quality``, ``evidence_citation``,
      ``matches_golden``).
    - **usedInAutoEval** — runs in `eval-trace-listener`'s always-on poll loop
      (see its ``LISTENER_SCORERS``).
    - **usedInEvalServiceWorker** — runs synchronously in the BPMN's eval
      service task (see `eval-service-worker`'s ``scoring.py``:
      ``decision_quality`` plus the plain ``DETERMINISTIC_SCORERS`` — neither
      ``evidence_citation``/``matches_golden`` nor the tool-argument scorers,
      which need data the worker's trace-only inputs don't carry).
    - **usedInRegression** — `regression/test_mlflow_regression.py` is the one
      place that exercises every scorer that exists (each per-golden test runs
      ``decision_quality``/``matches_golden``/``evidence_citation`` plus every
      entry in ``ALL_DETERMINISTIC_SCORERS``), so this is always ``True`` here — kept as an explicit field (rather than a
      hardcoded ``True`` in the response) so a future reader sees *why*, and
      so this stays correct if that ever changes.
    """
    from eval_trace_listener.scoring import LISTENER_SCORERS
    from fluxnova_mlflow_dataset.scorers import (
        ALL_DETERMINISTIC_SCORERS,
        DETERMINISTIC_SCORERS,
        decision_quality,
        evidence_citation,
        matches_golden,
    )

    # The full scorer universe — every scorer defined anywhere in the project.
    universe = [decision_quality, evidence_citation, matches_golden, *ALL_DETERMINISTIC_SCORERS]

    deterministic_names = {scorer.name for scorer in ALL_DETERMINISTIC_SCORERS}
    auto_eval_names = {scorer.name for scorer in LISTENER_SCORERS}
    # eval-service-worker builds its own decision_quality_judge(...) instance rather
    # than importing the shared `decision_quality` object, but it's the same scorer
    # by name (see eval_service_worker/scoring.py) — checking the name avoids
    # constructing a real judge model client just to compare identities.
    eval_service_worker_names = {scorer.name for scorer in DETERMINISTIC_SCORERS} | {
        decision_quality.name
    }

    return [
        {
            **_describe(scorer),
            "deterministic": scorer.name in deterministic_names,
            "usedInAutoEval": scorer.name in auto_eval_names,
            "usedInEvalServiceWorker": scorer.name in eval_service_worker_names,
            "usedInRegression": True,
        }
        for scorer in universe
    ]
