"""Collects newly-completed agentic subprocess runs and records them into
the persistent MLflow evaluation dataset.

This is the on-demand replacement for the old ``fluxnova_listener`` service.
Nothing here needs to run in the background or react to a live stream:

- MLflow already durably stores traces once the OTel Collector exports them
  (``otlphttp`` exporter -> MLflow's ``/v1/traces``), so they can be queried
  at any later time via ``MlflowTraceReader``.
- BPMN is a static file (``BpmnLookup``).
- Fluxnova's ``/history/variable-instance`` API keeps a completed instance's
  variables available long after the instance ends (``FluxnovaClient``).

So collection is just "join three already-persisted data sources and upsert
a dataset record" — safe to (re-)run on demand, e.g. as a pre-step before
``mlflow-eval``, rather than needing a resident daemon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mlflow

from fluxnova_mlflow_dataset.bpmn import BpmnLookup
from fluxnova_mlflow_dataset.fluxnova_client import FluxnovaClient
from fluxnova_mlflow_dataset.report import TraceReader, VariableReader, build_agent_report
from fluxnova_mlflow_dataset.store import (
    build_mlflow_record,
    experiment_name_for,
    write_to_mlflow_dataset,
)
from fluxnova_mlflow_dataset.tools import ExpectedToolRule
from fluxnova_mlflow_dataset.traces import MlflowTraceReader


@dataclass
class CollectedRun:
    """The outcome of collecting one completed run."""

    process_instance_id: str
    dataset_name: str
    record_id: str | None
    written: bool


def collect_new_runs(
    *,
    tracking_uri: str,
    fluxnova_url: str,
    process_key: str,
    subprocess_id: str,
    bpmn_path: Path,
    variable_names: list[str],
    available_tools: dict[str, str],
    expected_tool_rules: list[ExpectedToolRule],
    dataset_path: Path | None,
    dataset_name: str | None = None,
    experiment_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
    trace_reader: TraceReader | None = None,
    fluxnova_client: VariableReader | None = None,
    bpmn: BpmnLookup | None = None,
) -> list[CollectedRun]:
    """Find every completed run for ``subprocess_id`` in MLflow's trace store
    and upsert an evaluation-dataset record for each one not already present.

    Idempotent — safe to call repeatedly (e.g. before every ``mlflow-eval``
    invocation); already-recorded runs (matched by ``processInstanceId``) are
    skipped rather than re-written.

    The ``trace_reader``/``fluxnova_client``/``bpmn`` parameters are for
    dependency injection in tests; real callers should leave them unset.
    """
    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name_for(process_key, experiment_name))

    traces = trace_reader or MlflowTraceReader(tracking_uri, experiment.experiment_id)
    client = fluxnova_client or FluxnovaClient(base_url=fluxnova_url, username=username, password=password)
    bpmn_lookup = bpmn or BpmnLookup(bpmn_path, subprocess_id)

    results: list[CollectedRun] = []
    for instance_id, _agent_name in traces.find_completed_runs({subprocess_id}):
        agent_history = build_agent_report(client, bpmn_lookup, traces, instance_id, variable_names)
        record = build_mlflow_record(
            process_key=process_key,
            process_instance_id=instance_id,
            agent_goal=agent_history["goal"],
            input_variables=agent_history["inputVariables"],
            tool_calls=agent_history["toolCalls"],
            iterations=agent_history["iterations"],
            final_output=agent_history["finalOutput"],
            available_tools=list(available_tools.values()),
            expected_tool_rules=expected_tool_rules,
            dataset_path=dataset_path,
        )
        name, record_id, written = write_to_mlflow_dataset(
            tracking_uri=tracking_uri,
            process_key=process_key,
            dataset_name=dataset_name,
            record=record,
            experiment_name=experiment_name,
        )
        results.append(CollectedRun(instance_id, name, record_id, written))
    return results
