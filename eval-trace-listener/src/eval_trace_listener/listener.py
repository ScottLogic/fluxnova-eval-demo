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
            if the trace has finished (state OK), its invoke_agent span's agent
               name is one we care about, and we haven't already scored it:
                   score it with the deterministic scorers

Completion is the trace's own terminal state. MLflow assembles a *live* trace
as its subprocess runs: the root ``invoke_agent`` span is created up front and
``search_traces`` returns the trace (root span already present) while it's still
``IN_PROGRESS``. So the span's mere presence is NOT a "completed" signal — a
partial trace would be scored on incomplete data. Instead we gate on
``trace.info.state == OK`` (the root span has ended and the run succeeded), and
only then read the agent name off it. Dedup is belt-and-braces: an in-memory set of scored trace ids
(fast path) plus a check for our own scorer assessments already on the trace
(survives restarts, since assessments are persisted on the trace itself).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import DETERMINISTIC_SCORERS
from mlflow.entities.trace_state import TraceState

from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.control import SampleRateControl
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

# Scorers the *online* eval-service-worker also writes onto these same traces
# (decision_quality + the deterministic bundle — see eval-service-worker's
# README). Because the worker scores each eval-BPMN run synchronously, its
# assessments usually land on the trace before this listener polls it. So the
# mere presence of these assessment names does NOT mean *we* scored the trace —
# they're excluded from our dedup signature below, otherwise the listener would
# skip every trace the worker already touched and never add its own scorers
# (e.g. evidence_citation).
_WORKER_ONLINE_SCORER_NAMES = frozenset(
    {s.name for s in DETERMINISTIC_SCORERS} | {"decision_quality"}
)

# A trace whose span data can't be fetched (e.g. an async-write race for one that
# just landed) may fail to score; retry it a few cycles before giving up so one
# poison trace can't block every older unscored trace behind it forever.
_MAX_SCORING_ATTEMPTS = 3

# Tag the regression suite (regression/test_mlflow_regression.py) sets on every
# trace it generates. Regression runs share the exact same subprocess_id (and
# therefore the exact same gen_ai.agent.name) as real/demo runs, so agent_names
# filtering alone can't tell them apart — this tag is the only reliable signal.
_REGRESSION_TAG_NAME = "source"
_REGRESSION_TAG_VALUE = "regression"


class TraceListener:
    """Tails one MLflow experiment for completed agent runs and scores them."""

    def __init__(
        self,
        config: ListenerConfig,
        scorers: list[Any] | None = None,
        sample_rate: SampleRateControl | None = None,
    ) -> None:
        self._config = config
        # Own control instance by default (seeded from the static config), so the
        # listener works standalone; main.py passes in the same instance it hands
        # to the control HTTP server so PUT /config actually changes what's used
        # here, live.
        self._sample_rate = sample_rate or SampleRateControl(config.sample_rate)
        self._scorers = LISTENER_SCORERS if scorers is None else scorers
        self._scorer_names = {s.name for s in self._scorers}
        # Dedup signature: the scorer names that identify *this listener's* prior
        # scoring specifically. We drop the scorers the online worker also writes
        # (see _WORKER_ONLINE_SCORER_NAMES) so a trace the worker already scored
        # isn't mistaken for one we scored. Fall back to the full set if that
        # leaves nothing unique (e.g. a listener configured with only shared
        # scorers) so dedup can never silently disable and re-score every poll.
        self._signature_names = (
            self._scorer_names - _WORKER_ONLINE_SCORER_NAMES
        ) or self._scorer_names
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
            "eval-trace-listener starting: experiment=%r agents=%s poll=%.1fs "
            "sample_rate=%.2f tracking_uri=%s",
            self._config.experiment_name,
            self._config.agent_names or "<all>",
            self._config.poll_interval_s,
            self._sample_rate.get(),
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
            except Exception as exc:  # noqa: BLE001 - a poison trace must not wedge the loop
                # Any *unexpected* per-trace error (e.g. a malformed row) is treated
                # like a scoring failure: retried a few cycles then skipped, so a
                # single bad trace can never crash the cycle and reprocess forever.
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

        if not self._is_complete(trace):
            # Trace is still IN_PROGRESS (or errored): its live root span is
            # already visible but the subprocess hasn't finished, so scoring now
            # would run on a partial trace. Skip — a later poll re-checks it once
            # it reaches a terminal OK state.
            return False

        agent_name = self._agent_name(trace)
        if agent_name is None:
            # No invoke_agent span => not an agent trace.
            return False
        if self._config.agent_names and agent_name not in self._config.agent_names:
            return False

        if self._is_regression_trace(trace):
            # A regression-suite run, not a real/demo one — see the module-level
            # comment on _REGRESSION_TAG_NAME. Cache it as "scored" so we don't
            # re-inspect it every poll, without actually scoring it.
            self._scored.add(trace_id)
            return False

        if self._already_scored(trace):
            self._scored.add(trace_id)  # cache so we don't re-inspect it every poll
            return False

        if not self._should_sample():
            # A sampling decision is made (and remembered) exactly once per trace,
            # not re-rolled every poll — otherwise a trace that keeps reappearing
            # in _recent_traces would eventually get scored no matter how low the
            # rate, defeating the point of sampling.
            self._scored.add(trace_id)
            logger.info(
                "Skipping trace %s (agent=%s) — sample_rate=%.2f",
                trace_id,
                agent_name,
                self._sample_rate.get(),
            )
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

    def _handle_scoring_failure(self, trace_id: str, exc: Exception) -> None:
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

    def _should_sample(self) -> bool:
        """One-shot dice roll against the current sample rate (own method so
        tests can patch/seed it deterministically)."""
        rate = self._sample_rate.get()
        if rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        return random.random() < rate

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

    def _is_complete(self, trace: Any) -> bool:
        """True once ``trace`` has reached a terminal OK state.

        MLflow exposes a trace (root span included) while it's still
        ``IN_PROGRESS``, so completion must be read off the trace's own state
        rather than inferred from span presence. ``ERROR`` traces are treated as
        not-complete: the run failed, so there's no valid final output to score.
        """
        state = getattr(trace.info, "state", None)
        state_value = getattr(state, "value", state)
        return state_value == TraceState.OK.value

    def _agent_name(self, trace: Any) -> str | None:
        """Return the run's agent name off its invoke_agent span, or None if the
        trace has no invoke_agent span (i.e. it isn't an agent run).
        """
        for span in trace.data.spans:
            if span.get_attribute(_OP_NAME_ATTR) == _INVOKE_AGENT_OP:
                return span.get_attribute(_AGENT_NAME_ATTR)
        return None

    def _is_regression_trace(self, trace: Any) -> bool:
        """True if this trace was tagged by the regression suite as its own run.

        See the module-level comment on ``_REGRESSION_TAG_NAME`` for why this
        tag — not ``agent_names`` — is what actually distinguishes a regression
        run from a real/demo one.
        """
        tags = getattr(trace.info, "tags", None) or {}
        return tags.get(_REGRESSION_TAG_NAME) == _REGRESSION_TAG_VALUE

    def _already_scored(self, trace: Any) -> bool:
        """True if this trace already carries one of *our own* scorer assessments
        (see :attr:`_signature_names`) — so a restarted listener (empty in-memory
        set) doesn't re-score history. Assessments the online worker writes with
        overlapping scorer names are excluded from the signature, so they don't
        make us skip a trace we haven't scored ourselves yet.
        """
        assessments = getattr(trace.info, "assessments", None) or []
        return any(getattr(a, "name", None) in self._signature_names for a in assessments)
