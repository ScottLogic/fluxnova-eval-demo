"""Poll an MLflow experiment's trace store and score newly-completed agent runs.

Design (see the package README for the full rationale): the OTel Collector
already exports every agent trace straight to MLflow's native trace store, and
``mlflow.search_traces`` reads them back fully assembled — as the exact
``Trace`` object the deterministic scorers already consume. So rather than
standing up a bespoke OTLP receiver (the ``fluxnova_listener`` layer this repo
deliberately removed) and reassembling spans by hand, this service simply
*tails* that store:

    every poll_interval_s seconds:
        for each recent trace in the configured experiment:
            if its invoke_agent span's agent name is one we care about,
               the run is complete, and we haven't already scored it:
                   score it with the deterministic scorers

A run's ``invoke_agent`` (root) span is only exported once the subprocess has
ended (spans export on span-end, root last), so its presence *is* the
"completed" signal — the same one ``MlflowTraceReader.find_completed_runs``
relies on. Dedup is belt-and-braces: an in-memory set of scored trace ids
(fast path) plus a check for our own scorer assessments already on the trace
(survives restarts, since assessments are persisted on the trace itself).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import mlflow

from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.scoring import (
    LISTENER_SCORERS,
    ScoringError,
    TraceEvalOutcome,
    score_trace,
)

logger = logging.getLogger(__name__)

_OP_NAME_ATTR = "gen_ai.operation.name"
_AGENT_NAME_ATTR = "gen_ai.agent.name"
_INVOKE_AGENT_OP = "invoke_agent"

# A trace whose span data can't be fetched (e.g. an async-write race for one that
# just landed) may fail to score; retry it a few cycles before giving up so one
# poison trace can't block every older unscored trace behind it forever.
_MAX_SCORING_ATTEMPTS = 3


class TraceListener:
    """Tails one MLflow experiment for completed agent runs and scores them."""

    def __init__(self, config: ListenerConfig, scorers: list[Any] | None = None) -> None:
        self._config = config
        self._scorers = LISTENER_SCORERS if scorers is None else scorers
        self._scorer_names = {s.name for s in self._scorers}
        self._experiment_id: str | None = None
        # trace ids scored during this process's lifetime (fast-path dedup).
        self._scored: set[str] = set()
        # trace ids -> failed scoring attempts, so we can give up on poison traces.
        self._failures: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Poll until interrupted (Ctrl+C)."""
        logger.info(
            "eval-trace-listener starting: experiment=%r agents=%s poll=%.1fs tracking_uri=%s",
            self._config.experiment_name,
            self._config.agent_names or "<all>",
            self._config.poll_interval_s,
            self._config.tracking_uri,
        )
        try:
            while True:
                try:
                    scored = self.run_once()
                    if scored:
                        logger.info("Scored %d new trace(s) this cycle.", scored)
                except Exception:  # noqa: BLE001 - never let one bad cycle kill the loop
                    logger.exception("Poll cycle failed; retrying after the poll interval")
                time.sleep(self._config.poll_interval_s)
        except KeyboardInterrupt:
            logger.info("Shutting down eval-trace-listener.")

    def run_once(self) -> int:
        """Run a single poll cycle; return how many new traces were scored.

        Self-contained: points MLflow at the configured tracking store first, so
        it works standalone (not only when driven by :meth:`run_forever`).
        """
        mlflow.set_tracking_uri(self._config.tracking_uri)
        experiment_id = self._resolve_experiment_id()
        if experiment_id is None:
            logger.info(
                "Experiment %r not found yet — waiting for traces to land.",
                self._config.experiment_name,
            )
            return 0
        # Ensure the grouping Evaluation Run mlflow.genai.evaluate opens lands in the
        # same experiment the traces live in (rather than the ambient default).
        mlflow.set_experiment(experiment_id=experiment_id)

        scored = 0
        for trace in self._recent_traces(experiment_id):
            try:
                if self._process_trace(trace):
                    scored += 1
            except ScoringError as exc:
                # One un-scoreable trace must not abort the cycle and starve every
                # older unscored trace behind it. Retry a few cycles, then give up.
                self._handle_scoring_failure(trace.info.trace_id, exc)
        return scored

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _process_trace(self, trace: Any) -> bool:
        """Score ``trace`` if it's a completed, in-scope, not-yet-scored run.

        Returns True only when this call actually scored the trace.
        """
        trace_id = trace.info.trace_id
        if trace_id in self._scored:
            return False

        agent_name = self._agent_name(trace)
        if agent_name is None:
            # No invoke_agent span yet => run not complete (or not an agent trace).
            return False
        if self._config.agent_names and agent_name not in self._config.agent_names:
            return False

        if self._already_scored(trace):
            self._scored.add(trace_id)  # cache so we don't re-inspect it every poll
            return False

        outcome = self._score(trace)
        self._scored.add(trace_id)
        self._failures.pop(trace_id, None)
        logger.info(
            "Scored trace %s (agent=%s): passed=%s [%s]",
            trace_id,
            agent_name,
            outcome.passed,
            outcome.summary(),
        )
        return True

    def _handle_scoring_failure(self, trace_id: str, exc: ScoringError) -> None:
        """Record a failed scoring attempt; give up (skip) after the retry budget."""
        attempts = self._failures.get(trace_id, 0) + 1
        self._failures[trace_id] = attempts
        if attempts >= _MAX_SCORING_ATTEMPTS:
            self._scored.add(trace_id)  # stop retrying this poison trace
            self._failures.pop(trace_id, None)
            logger.warning(
                "Giving up on trace %s after %d failed scoring attempts: %s",
                trace_id,
                attempts,
                exc,
            )
        else:
            logger.warning(
                "Failed to score trace %s (attempt %d/%d); will retry next cycle: %s",
                trace_id,
                attempts,
                _MAX_SCORING_ATTEMPTS,
                exc,
            )

    def _score(self, trace: Any) -> TraceEvalOutcome:
        """Score one trace (own method so tests can patch it)."""
        return score_trace(trace, self._scorers)

    def _resolve_experiment_id(self) -> str | None:
        if self._experiment_id is not None:
            return self._experiment_id
        experiment = mlflow.get_experiment_by_name(self._config.experiment_name)
        if experiment is None:
            return None
        self._experiment_id = experiment.experiment_id
        return self._experiment_id

    def _recent_traces(self, experiment_id: str) -> list[Any]:
        return mlflow.search_traces(
            locations=[experiment_id],
            max_results=self._config.max_traces_per_poll,
            order_by=["timestamp_ms DESC"],
            return_type="list",
        )

    def _agent_name(self, trace: Any) -> str | None:
        """Return the run's agent name off its invoke_agent span, or None if the
        trace has no invoke_agent span (i.e. it isn't a completed agent run).
        """
        for span in trace.data.spans:
            if span.get_attribute(_OP_NAME_ATTR) == _INVOKE_AGENT_OP:
                return span.get_attribute(_AGENT_NAME_ATTR)
        return None

    def _already_scored(self, trace: Any) -> bool:
        """True if this trace already carries one of our scorer assessments —
        so a restarted listener (empty in-memory set) doesn't re-score history.
        """
        assessments = getattr(trace.info, "assessments", None) or []
        return any(getattr(a, "name", None) in self._scorer_names for a in assessments)
