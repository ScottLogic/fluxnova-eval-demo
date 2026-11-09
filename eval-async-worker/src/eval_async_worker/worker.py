"""External-task worker for the non-blocking Eval service task.

``bpmn/LoanApprovalProcess_AI.bpmn`` forks the run after the agent call
(``Gateway_ForkAsyncEval``). One branch carries on with the loan; the other
reaches ``ServiceTask_AsyncEvaluateAgentOutput`` (topic
``agent-output-eval-async``), which this worker serves:

    for each locked task:
        resolve the agent's (Call Activity child) process instance
        roll the sample-rate dice; if not sampled, complete straight away
        read the run's scorer inputs from its process variables
        wait for that run's trace to land in MLflow (the anchor for feedback)
        score it with ASYNC_EVAL_SCORERS (assessments logged onto the trace)
        complete the task with NO variables

Scorer inputs never come from trace content, so gen_ai content capture can
stay off; see ``fluxnova_mlflow_dataset.process_variables``.

Completing with no variables is deliberate: the parallel token shares the
process scope, so writing results here could change how the other branch
routes. The branches never join, so nothing in the loan process waits on this
task. Failures are reported to Fluxnova (retried, then an incident on this
task only).

This replaces the earlier design that polled MLflow's trace store for any
completed agent run. Scoring is now triggered by the process itself, once per
run, so there's no dedup state, no agent-name filter and no regression-run
filter to maintain.
"""

from __future__ import annotations

import logging
import random
import threading
from typing import Any

import mlflow
import requests
from camunda.external_task.external_task import ExternalTask
from camunda.external_task.external_task_worker import ExternalTaskWorker
from fluxnova_mlflow_dataset import (
    AgentRun,
    ApiError,
    FluxnovaClient,
    MlflowTraceReader,
    TraceStoreError,
    load_agent_run,
)

from eval_async_worker.config import AsyncWorkerConfig
from eval_async_worker.control import SampleRateControl
from eval_async_worker.scoring import ASYNC_EVAL_SCORERS, ScoringError, score_trace

logger = logging.getLogger(__name__)

# Retry budget for transient failures (trace not delivered yet, span data not
# readable yet). Once Camunda's retry count hits 0 the task becomes an incident.
_MAX_RETRIES = 3
_RETRY_TIMEOUT_MS = 10_000
# Idle fetch long-poll, kept separate from the long task lease used for judging.
_ASYNC_RESPONSE_TIMEOUT_MS = 10_000


class AsyncEvalWorker:
    """Scores the agent run behind each ``agent-output-eval-async`` task."""

    def __init__(
        self,
        config: AsyncWorkerConfig,
        client: FluxnovaClient | None = None,
        scorers: list[Any] | None = None,
        sample_rate: SampleRateControl | None = None,
    ) -> None:
        self._config = config
        self._client = client or FluxnovaClient(config.fluxnova_url)
        self._scorers = ASYNC_EVAL_SCORERS if scorers is None else scorers
        # main.py passes in the same instance it hands to the control HTTP
        # server, so PUT /config changes the rate used here, live.
        self._sample_rate = sample_rate or SampleRateControl(config.sample_rate)
        self._experiment_id: str | None = None

    # ------------------------------------------------------------------
    # External-task handler
    # ------------------------------------------------------------------

    def handle(self, task: ExternalTask) -> Any:
        parent_id = task.get_process_instance_id()
        instance_id = self._agent_instance_id(parent_id)

        if not self._should_sample():
            logger.info(
                "Skipping %s (sample_rate=%.2f) — completing without scoring",
                instance_id,
                self._sample_rate.get(),
            )
            return task.complete()

        try:
            run = self._load_run(instance_id)
        except (ApiError, requests.RequestException) as exc:
            logger.warning("Could not read process variables for %s: %s", instance_id, exc)
            return task.failure(
                error_message="Could not read the agent run's process variables",
                error_details=str(exc),
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        if not run.outputs:
            logger.warning("No final output in the process variables of %s", instance_id)
            return task.failure(
                error_message="No final agent output to score",
                error_details=f"_agentConversationHistory of {instance_id} has no assistant reply",
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )

        try:
            trace = self._fetch_trace(instance_id)
            outcome = self._score(trace, run)
        except (TraceStoreError, ScoringError) as exc:
            logger.warning("Trace for %s not ready to score: %s", instance_id, exc)
            return task.failure(
                error_message="Agent trace not yet available to score",
                error_details=str(exc),
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        except Exception as exc:  # noqa: BLE001 - report every unexpected failure to Fluxnova
            logger.exception("Async eval failed for %s", instance_id)
            return task.failure(
                error_message="eval-async-worker scoring failed",
                error_details=str(exc),
                max_retries=0,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )

        logger.info(
            "Scored %s (trace %s): passed=%s [%s]",
            instance_id,
            outcome.trace_id,
            outcome.passed,
            outcome.summary(),
        )
        return task.complete()

    # ------------------------------------------------------------------
    # Internals (own methods so tests can patch them)
    # ------------------------------------------------------------------

    def _agent_instance_id(self, parent_id: str) -> str:
        """The agent runs in a Call Activity child instance, and its trace is
        tagged with the child's id. Fall back to the parent if there's no child
        or the lookup fails."""
        try:
            return self._client.get_child_instance_id(parent_id) or parent_id
        except (ApiError, requests.RequestException) as exc:
            logger.warning("Could not resolve child instance for %s (%s)", parent_id, exc)
            return parent_id

    def _load_run(self, instance_id: str) -> AgentRun:
        return load_agent_run(self._client, instance_id)

    def _should_sample(self) -> bool:
        rate = self._sample_rate.get()
        if rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        return random.random() < rate

    def _experiment(self) -> str:
        if self._experiment_id is None:
            mlflow.set_tracking_uri(self._config.tracking_uri)
            experiment = mlflow.set_experiment(self._config.experiment_name)
            self._experiment_id = experiment.experiment_id
        return self._experiment_id

    def _fetch_trace(self, instance_id: str) -> Any:
        reader = MlflowTraceReader(self._config.tracking_uri, self._experiment())
        return reader.wait_for_trace(
            instance_id,
            timeout=self._config.trace_poll_timeout_s,
            poll_interval=self._config.trace_poll_interval_s,
        )

    def _score(self, trace: Any, run: AgentRun) -> Any:
        # Make sure the Evaluation Run lands in the traces' experiment.
        mlflow.set_experiment(experiment_id=self._experiment())
        return score_trace(trace, run.inputs, run.outputs, self._scorers)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run_forever(self, username: str | None = None, password: str | None = None) -> None:
        """Subscribe to the topic and block until interrupted (Ctrl+C)."""
        worker_config: dict[str, Any] = {
            "maxTasks": 1,
            "lockDuration": self._config.lock_duration_ms,
            "asyncResponseTimeout": _ASYNC_RESPONSE_TIMEOUT_MS,
            "retries": _MAX_RETRIES,
            "retryTimeout": _RETRY_TIMEOUT_MS,
            "sleepSeconds": 2,
        }
        if username or password:
            worker_config["auth_basic"] = {"username": username or "", "password": password or ""}

        worker = ExternalTaskWorker(
            worker_id="eval-async-worker",
            base_url=self._config.fluxnova_url,
            config=worker_config,
        )
        logger.info(
            "eval-async-worker subscribing to topic %r at %s (sample_rate=%.2f)",
            self._config.topic,
            self._config.fluxnova_url,
            self._sample_rate.get(),
        )
        thread = threading.Thread(
            target=worker.subscribe,
            args=([self._config.topic], self.handle),
            daemon=True,
            name=f"worker-{self._config.topic}",
        )
        thread.start()
        try:
            thread.join()
        except KeyboardInterrupt:
            logger.info("Shutting down eval-async-worker.")
