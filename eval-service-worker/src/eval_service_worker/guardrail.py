"""Guardrail thresholds: decide pass/fail from per-scorer results.

The thresholds live in the BPMN, not in this worker, so they can be changed in
the Modeler without redeploying the Eval service. The Eval service task declares
them as ``camunda:inputParameter``s (local to the task, and visible to the
worker as task variables):

- ``evalMinScore`` (number, 0.0–1.0): the minimum fraction of *applicable*
  scorers that must pass. ``1.0`` (the default) means every scorer must pass.
- ``evalRequiredScorers`` (comma-separated scorer names): scorers that must pass
  whatever the score, e.g. ``decision_quality``. Empty means none.

A scorer that returns no verdict (``None``/``NaN``: not applicable to this run)
is left out of the score entirely, so it can neither pass nor fail the run.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

MIN_SCORE_VAR = "evalMinScore"
REQUIRED_SCORERS_VAR = "evalRequiredScorers"

DEFAULT_MIN_SCORE = 1.0


class GuardrailConfigError(ValueError):
    """Raised when the task's threshold variables are invalid."""


@dataclass(frozen=True)
class GuardrailThresholds:
    min_score: float = DEFAULT_MIN_SCORE
    required_scorers: tuple[str, ...] = ()

    @classmethod
    def from_task_variables(
        cls, get_variable: Callable[[str], Any], known_scorers: Iterable[str]
    ) -> GuardrailThresholds:
        """Read and validate the thresholds from the external task's variables.

        Missing variables fall back to the defaults (every scorer must pass,
        none specially required), which matches a BPMN with no thresholds set.
        """
        raw_min = get_variable(MIN_SCORE_VAR)
        if raw_min is None or (isinstance(raw_min, str) and not raw_min.strip()):
            min_score = DEFAULT_MIN_SCORE
        else:
            try:
                min_score = float(raw_min)
            except (TypeError, ValueError) as exc:
                raise GuardrailConfigError(
                    f"{MIN_SCORE_VAR} must be a number between 0 and 1, got {raw_min!r}"
                ) from exc
            if math.isnan(min_score) or not 0.0 <= min_score <= 1.0:
                raise GuardrailConfigError(
                    f"{MIN_SCORE_VAR} must be between 0 and 1, got {raw_min!r}"
                )

        raw_required = get_variable(REQUIRED_SCORERS_VAR) or ""
        if not isinstance(raw_required, str):
            raise GuardrailConfigError(
                f"{REQUIRED_SCORERS_VAR} must be a comma-separated string, got {raw_required!r}"
            )
        required = tuple(name.strip() for name in raw_required.split(",") if name.strip())
        unknown = sorted(set(required) - set(known_scorers))
        if unknown:
            raise GuardrailConfigError(
                f"{REQUIRED_SCORERS_VAR} names unknown scorer(s) {unknown}; "
                f"known scorers: {sorted(known_scorers)}"
            )
        return cls(min_score=min_score, required_scorers=required)


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    # Fraction of applicable scorers that passed (1.0 when none were applicable).
    score: float
    # Every applicable scorer that failed, in scorer order.
    failed: tuple[str, ...]
    # The subset of ``failed`` listed in ``required_scorers``.
    required_failed: tuple[str, ...]


def _is_not_applicable(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def apply_guardrail(
    scorer_results: dict[str, dict[str, Any]],
    thresholds: GuardrailThresholds,
    scorer_passed: Callable[[str, Any], bool],
) -> GuardrailResult:
    """Apply ``thresholds`` to one run's ``{scorer: {"value", "rationale"}}`` results.

    ``scorer_passed(name, value)`` decides whether one applicable verdict passes.
    """
    applicable = {
        name: res for name, res in scorer_results.items() if not _is_not_applicable(res["value"])
    }
    failed = tuple(name for name, res in applicable.items() if not scorer_passed(name, res["value"]))
    score = 1.0 if not applicable else (len(applicable) - len(failed)) / len(applicable)
    # A required scorer with no verdict (not applicable to this run) doesn't fail it.
    required_failed = tuple(name for name in thresholds.required_scorers if name in failed)
    passed = not required_failed and score >= thresholds.min_score
    return GuardrailResult(
        passed=passed, score=score, failed=failed, required_failed=required_failed
    )
