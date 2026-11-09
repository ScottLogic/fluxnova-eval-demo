"""BPMN external-task worker: scores a just-completed agentic subprocess run.

Subscribes to a single Camunda/Fluxnova external-task topic (default
``agent-output-eval``). On each task, reads the agent run's process variables
from Fluxnova (see ``scoring.py``), runs the ``decision_quality`` judge plus a set of
deterministic scorers (see ``scoring.py``), logs the results to MLflow (trace
assessments + an Evaluation Run + a dataset record), and completes the task
with ``evalPassed``/``evalRationale``/``evalScore``/``evalFailedScorers`` output
variables; ``evalPassed`` drives the BPMN gateway.

Pass/fail thresholds come from the task's own variables, declared as
``camunda:inputParameter``s on the Eval service task so they can be changed in
the Modeler (see ``guardrail.py``): ``evalMinScore`` (default 1.0, i.e. every
applicable scorer must pass) and ``evalRequiredScorers``.
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import UTC, datetime
from typing import Any

import requests
from camunda.external_task.external_task import ExternalTask
from camunda.external_task.external_task_worker import ExternalTaskWorker
from fluxnova_mlflow_dataset import (
    DECISION_QUALITY_NAME,
    DETERMINISTIC_SCORERS,
    ApiError,
    FluxnovaClient,
    TraceStoreError,
)

from eval_service_worker.config import EvalServiceConfig
from eval_service_worker.guardrail import GuardrailConfigError, GuardrailThresholds
from eval_service_worker.scoring import NoFinalOutputError, score_process_instance

logger = logging.getLogger(__name__)

# Retries a few times (a transient MLflow/network failure, or the trace not having
# landed yet within DEFAULT_TRACE_POLL_TIMEOUT_S) before giving up on a task and
# leaving it for manual/BPMN-level intervention — once Camunda's retry count hits 0
# it does NOT automatically retry the task again, so too small a budget here
# permanently stalls the BPMN gate rather than just being slow.
# Every scorer name the guardrail can be configured with (evalRequiredScorers).
_KNOWN_SCORERS = frozenset({DECISION_QUALITY_NAME, *(s.name for s in DETERMINISTIC_SCORERS)})

_MAX_RETRIES = 3
_RETRY_TIMEOUT_MS = 10_000
# Idle fetch wait is separate from the task lease needed for slow judging.
# A ten-minute long poll can acquire a new task long after its client shuts down.
_ASYNC_RESPONSE_TIMEOUT_MS = 10_000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_camunda_vars(variables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    type_map = {str: "String", int: "Integer", float: "Double", bool: "Boolean"}
    return {
        name: {"value": value, "type": type_map.get(type(value), "String")}
        for name, value in variables.items()
    }


def _resolve_agent_instance_id(client: FluxnovaClient | None, parent_instance_id: str) -> str:
    """Return the instance id whose trace the agent actually produced.

    Since the agent runs in a callable subprocess (``loanAssessmentProcess``)
    invoked via a Call Activity, its trace is tagged with the *child* instance
    id — not the parent (eval) instance id the external task belongs to. Look up
    that child instance so scoring correlates against the right trace. Falls
    back to the parent id if there's no child (e.g. the agent is inline) or the
    lookup fails, so scoring still proceeds on a best-effort basis.
    """
    if client is None:
        return parent_instance_id
    try:
        child_id = client.get_child_instance_id(parent_instance_id)
    except (ApiError, requests.RequestException) as exc:
        logger.warning(
            "Could not resolve child instance for %s (%s) — scoring parent instead",
            parent_instance_id,
            exc,
        )
        return parent_instance_id
    if child_id:
        print(
            f"[{_now()}] RESOLVE parent={parent_instance_id} -> agent child={child_id}"
        )
        return child_id
    return parent_instance_id


def make_handler(config: EvalServiceConfig, client: FluxnovaClient | None = None):
    """Build the external-task handler function for :func:`run`.

    ``client`` is a read-only Fluxnova REST client used to resolve the agent's
    (child) process instance from the parent instance the external task belongs
    to; defaults to one built from ``config.fluxnova_url``.
    """
    if client is None:
        client = FluxnovaClient(config.fluxnova_url)

    def handle(task: ExternalTask):
        parent_instance_id = task.get_process_instance_id()
        process_instance_id = _resolve_agent_instance_id(client, parent_instance_id)
        print(f"[{_now()}] LOCKED  topic={config.topic} processInstanceId={process_instance_id}")
        # Validate the BPMN-supplied thresholds before spending a judge call.
        try:
            thresholds = GuardrailThresholds.from_task_variables(task.get_variable, _KNOWN_SCORERS)
        except GuardrailConfigError as exc:
            logger.error("Invalid guardrail thresholds on %s: %s", process_instance_id, exc)
            return task.failure(
                error_message="Invalid guardrail thresholds on the Eval service task",
                error_details=str(exc),
                max_retries=0,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        try:
            outcome = score_process_instance(
                process_instance_id,
                client=client,
                tracking_uri=config.tracking_uri,
                process_key=config.process_key,
                experiment_name=config.experiment_name,
                judge_model=config.judge_model,
                trace_poll_timeout=config.trace_poll_timeout,
                trace_poll_interval=config.trace_poll_interval,
                thresholds=thresholds,
            )
        except NoFinalOutputError as exc:
            logger.warning("No output to score yet for %s: %s", process_instance_id, exc)
            return task.failure(
                error_message="No final output available to score yet",
                error_details=str(exc),
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        except (ApiError, requests.RequestException) as exc:
            logger.warning("Could not read process variables for %s: %s", process_instance_id, exc)
            return task.failure(
                error_message="Could not read the agent run's process variables",
                error_details=str(exc),
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        except TraceStoreError as exc:
            # The internal poll in score_process_instance (config.trace_poll_timeout)
            # already gave the collector a chance to deliver the trace — this is a
            # backstop for slower deliveries, retried once more at the Camunda level.
            logger.warning("Trace not yet available for %s: %s", process_instance_id, exc)
            return task.failure(
                error_message="Trace not yet available to score",
                error_details=str(exc),
                max_retries=_MAX_RETRIES,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )
        except Exception as exc:  # noqa: BLE001 - report every unexpected failure to Camunda
            logger.exception("Scoring failed for %s", process_instance_id)
            return task.failure(
                error_message="eval-service-worker scoring failed",
                error_details=str(exc),
                max_retries=0,
                retry_timeout=_RETRY_TIMEOUT_MS,
            )

        outputs = {
            "evalPassed": outcome.eval_passed,
            "evalRationale": outcome.eval_rationale,
            "evalScore": float(outcome.eval_score),
            "evalFailedScorers": ",".join(outcome.failed_scorers),
        }
        result = task.complete(global_variables=_to_camunda_vars(outputs))
        print(
            f"[{_now()}] DONE    topic={config.topic} processInstanceId={process_instance_id} "
            f"evalPassed={outcome.eval_passed} evalScore={outcome.eval_score:.2f}"
        )
        return result

    return handle


def run(config: EvalServiceConfig, username: str | None = None, password: str | None = None) -> None:
    """Start the worker and block until interrupted (Ctrl+C)."""
    worker_config: dict[str, Any] = {
        "maxTasks": 1,
        "lockDuration": config.lock_duration_ms,
        "asyncResponseTimeout": _ASYNC_RESPONSE_TIMEOUT_MS,
        "retries": _MAX_RETRIES,
        "retryTimeout": _RETRY_TIMEOUT_MS,
        "sleepSeconds": 2,
    }
    if username or password:
        worker_config["auth_basic"] = {"username": username or "", "password": password or ""}

    worker = ExternalTaskWorker(
        worker_id="eval-service-worker",
        base_url=config.fluxnova_url,
        config=worker_config,
    )
    client = FluxnovaClient(config.fluxnova_url, username=username, password=password)
    print(f"eval-service-worker subscribing to topic '{config.topic}' at {config.fluxnova_url}")
    thread = threading.Thread(
        target=worker.subscribe,
        args=([config.topic], make_handler(config, client)),
        daemon=True,
        name=f"worker-{config.topic}",
    )
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nShutting down eval-service-worker.", file=sys.stderr)
