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

Two more task inputs decide which runs are scored and which go to human review
(see :class:`ReviewPolicy`):

- ``evalSampleRate`` (number, 0.0–1.0): the fraction of runs the guardrail
  scores. ``1.0`` (the default) scores every run. An unsampled run is completed
  without scoring and carries on without review.
- ``forceReviewEveryN`` (whole number): send every Nth run of the process to
  human review whatever its score (it is always scored, so the reviewer sees the
  result). ``0`` (the default) turns this off. The run number comes from the
  engine's history, so the count survives worker restarts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

MIN_SCORE_VAR = "evalMinScore"
REQUIRED_SCORERS_VAR = "evalRequiredScorers"
SAMPLE_RATE_VAR = "evalSampleRate"
FORCE_REVIEW_EVERY_N_VAR = "forceReviewEveryN"

DEFAULT_MIN_SCORE = 1.0
DEFAULT_SAMPLE_RATE = 1.0
DEFAULT_FORCE_REVIEW_EVERY_N = 0

# reviewReason values, comma-separated when more than one applies.
REASON_FAILED_EVAL = "FAILED_EVAL"
REASON_FORCED_EVERY_N = "FORCED_EVERY_N"


class GuardrailConfigError(ValueError):
    """Raised when the task's threshold variables are invalid."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _fraction(get_variable: Callable[[str], Any], name: str, default: float) -> float:
    raw = get_variable(name)
    if _blank(raw):
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise GuardrailConfigError(f"{name} must be a number between 0 and 1, got {raw!r}") from exc
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        raise GuardrailConfigError(f"{name} must be between 0 and 1, got {raw!r}")
    return value


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
        min_score = _fraction(get_variable, MIN_SCORE_VAR, DEFAULT_MIN_SCORE)

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


@dataclass(frozen=True)
class ReviewPolicy:
    """Which runs the guardrail scores, and which are forced to human review."""

    sample_rate: float = DEFAULT_SAMPLE_RATE
    force_review_every_n: int = DEFAULT_FORCE_REVIEW_EVERY_N

    @classmethod
    def from_task_variables(cls, get_variable: Callable[[str], Any]) -> ReviewPolicy:
        sample_rate = _fraction(get_variable, SAMPLE_RATE_VAR, DEFAULT_SAMPLE_RATE)
        raw_n = get_variable(FORCE_REVIEW_EVERY_N_VAR)
        if _blank(raw_n):
            every_n = DEFAULT_FORCE_REVIEW_EVERY_N
        else:
            try:
                every_n = float(raw_n)
            except (TypeError, ValueError) as exc:
                raise GuardrailConfigError(
                    f"{FORCE_REVIEW_EVERY_N_VAR} must be a whole number of 0 or more, got {raw_n!r}"
                ) from exc
            if math.isnan(every_n) or every_n < 0 or every_n != int(every_n):
                raise GuardrailConfigError(
                    f"{FORCE_REVIEW_EVERY_N_VAR} must be a whole number of 0 or more, got {raw_n!r}"
                )
            every_n = int(every_n)
        return cls(sample_rate=sample_rate, force_review_every_n=every_n)

    def is_forced(self, run_number: int | None) -> bool:
        """Whether this run is one of every N that must be reviewed."""
        return (
            self.force_review_every_n > 0
            and run_number is not None
            and run_number % self.force_review_every_n == 0
        )

    def is_sampled(self, forced: bool, roll: float) -> bool:
        """Whether to score this run. Forced runs are always scored; otherwise
        ``roll`` (uniform in [0, 1)) must fall below the sample rate."""
        return forced or roll < self.sample_rate


def review_reasons(*, sampled: bool, passed: bool | None, forced: bool) -> tuple[str, ...]:
    """Why a run goes to human review; empty when it doesn't."""
    reasons = []
    if sampled and passed is False:
        reasons.append(REASON_FAILED_EVAL)
    if forced:
        reasons.append(REASON_FORCED_EVERY_N)
    return tuple(reasons)
