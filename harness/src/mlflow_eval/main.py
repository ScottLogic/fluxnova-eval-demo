"""MLflow GenAI evaluation for the Fluxnova loan assessment agent subprocess.

Uses ``mlflow.genai.evaluate`` and MLflow scorers to evaluate the agent's
loan-assessment behaviour.

Two ways to select what to evaluate (use forward slashes for paths — on
Windows Git Bash / MINGW64, backslashes are treated as escape characters and
will mangle the path):

    # A single previously recorded run, read back from the MLflow dataset
    mlflow-eval config/loan-assesment.yml --instance-id <processInstanceId>

    # Every run currently recorded in the MLflow dataset for this process_key
    mlflow-eval config/loan-assesment.yml --all

Add ``--collect`` to either of the above (or on its own) to first pull newly-
completed agentic subprocess runs out of MLflow's trace store (populated by
an OTel Collector exporting straight to MLflow) and record them into the
MLflow evaluation dataset before evaluating. This is an on-demand replacement
for the old always-running ``fluxnova-listener`` service — nothing about
collection needs a background process, since BPMN, MLflow traces, and
Fluxnova's variable history are all already persisted by the time you run
this:

    mlflow-eval config/loan-assesment.yml --collect --all
    mlflow-eval config/loan-assesment.yml --collect            # collect only, don't evaluate

Results are written to a PostgreSQL-backed MLflow tracking store (see
``local-dev/postgres-up.sh`` — replaces the previous SQLite-file default) and can be
browsed with:
    mlflow ui --backend-store-uri postgresql://mlflow:mlflow@localhost:5432/mlflow

A summary of the aggregate scorer metrics (MLflow's own ``EvaluationResult``
summary, not a bespoke report) is also printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import BATCH_SCORERS, collect_new_runs

from fluxnova.config import WorkflowConfig
from fluxnova.mlflow_dataset import (
    dataset_name_for,
    experiment_name_for,
    get_or_create_dataset,
    tracking_uri_for,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# All scorer/judge definitions (including `BATCH_SCORERS` used below, and
# `automatic_judges`/`GATEWAY_JUDGE_MODEL` used by `fluxnova_mlflow_dataset.judges`) now
# live in `fluxnova_mlflow_dataset.scorers` — the single source of truth
# shared with `eval-service-worker`.


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_instance_row(dataset_name: str, experiment_id: str, instance_id: str):
    """Fetch one previously recorded run from the MLflow dataset, by processInstanceId."""
    dataset = get_or_create_dataset(dataset_name, experiment_id)
    df = dataset.to_df()
    matches = df[df["tags"].apply(lambda t: t.get("processInstanceId") == instance_id)]
    if matches.empty:
        raise SystemExit(
            f"No record with processInstanceId={instance_id!r} found in MLflow dataset "
            f"'{dataset_name}'. Was it recorded with mlflow_dataset.enabled: true?"
        )
    return matches


def _collect(config: WorkflowConfig, tracking_uri: str) -> None:
    """Pull newly-completed runs out of MLflow's trace store and record them into the dataset.

    On-demand replacement for the old ``fluxnova-listener`` polling service —
    see the module docstring above and ``proposal.md``.
    """
    if not config.subprocess_id:
        raise SystemExit("--collect requires 'subprocess_id' to be set in the workflow config")
    results = collect_new_runs(
        tracking_uri=tracking_uri,
        fluxnova_url=config.fluxnova_url,
        process_key=config.process_key,
        subprocess_id=config.subprocess_id,
        bpmn_path=config.bpmn_path,
        variable_names=list(config.variables.keys()),
        available_tools=config.available_tools,
        expected_tool_rules=config.expected_tools,
        dataset_path=config.dataset_path,
        dataset_name=config.mlflow_dataset.name if config.mlflow_dataset else None,
        experiment_name=config.mlflow_dataset.experiment_name if config.mlflow_dataset else None,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )
    if not results:
        print("--collect: no newly-completed runs found in MLflow's trace store.")
        return
    for run in results:
        status = f"recorded (record_id={run.record_id})" if run.written else "already recorded — skipped"
        print(f"--collect: processInstanceId={run.process_instance_id} -> {status}")


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run MLflow GenAI evaluation against Fluxnova agent-history data"
    )
    parser.add_argument("config", type=Path, help="Path to the workflow YAML config file")
    parser.add_argument(
        "--instance-id",
        default=None,
        help="Evaluate one previously recorded run from the MLflow dataset, by processInstanceId",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every run currently recorded in the MLflow dataset for this process_key",
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help=(
            "First pull newly-completed runs out of MLflow's trace store and record them into "
            "the dataset (see module docstring). May be combined with --all/--instance-id, or "
            "used on its own to only collect without evaluating."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    selected = [bool(args.instance_id), args.all]
    if sum(selected) > 1:
        parser.error("Specify at most one of: --instance-id or --all")
    if sum(selected) == 0 and not args.collect:
        parser.error("Specify one of: --instance-id, --all, or --collect")

    config = WorkflowConfig.from_file(args.config)
    tracking_uri = tracking_uri_for(config, _REPO_ROOT)
    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name_for(config))
    dataset_name = dataset_name_for(config)

    if args.collect:
        _collect(config, tracking_uri)

    if not any([args.instance_id, args.all]):
        return  # --collect only, nothing to evaluate

    if args.instance_id:
        data: Any = _load_instance_row(dataset_name, experiment.experiment_id, args.instance_id)
    else:
        data = get_or_create_dataset(dataset_name, experiment.experiment_id)

    result = mlflow.genai.evaluate(data=data, scorers=BATCH_SCORERS)

    print("\n=== MLflow evaluation summary ===")
    print(json.dumps(result.metrics, indent=2, default=str))
    print(
        "\nBrowse full results with:\n"
        f"  mlflow ui --backend-store-uri {tracking_uri}"
    )


if __name__ == "__main__":
    main()
