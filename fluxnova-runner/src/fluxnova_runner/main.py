"""Entry point for the standalone Fluxnova automated-run service.

Reads a YAML config file, deploys the specified BPMN to Fluxnova, optionally
starts mock external-task workers, starts a process instance, and polls
until it completes. Reporting/evaluation is *not* this service's job — run
``mlflow-eval <config> --collect`` afterwards (or independently, any time
later) to pull the completed agentic subprocess run out of MLflow's trace
store and record it into the MLflow evaluation dataset.

Usage
-----
    fluxnova-run config/workflow.yml
    fluxnova-run --skip-deploy config/workflow.yml
    fluxnova-run --with-mock-workers config/workflow.yml
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from fluxnova_runner.client import Client
from fluxnova_runner.config import RunnerConfig


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy and start a Fluxnova workflow")
    parser.add_argument("config", type=Path, help="Path to the workflow YAML config file")
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip BPMN deployment (use if already deployed)",
    )
    parser.add_argument(
        "--with-mock-workers",
        action="store_true",
        help="Start mock external task workers alongside the process",
    )
    parser.add_argument(
        "--wait-for-activity",
        metavar="ACTIVITY_ID",
        help=(
            "Instead of waiting for the whole process to finish, return as soon as "
            "this BPMN activity (e.g. AdHocSubProcess_LoanAssessmentAgent) completes "
            "— useful when a downstream step (like an eval service task) shouldn't "
            "block this run from being considered done."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def deploy(config: RunnerConfig, client: Client, skip: bool) -> None:
    if not skip:
        print(f"Deploying {config.bpmn_path} …")
        deployment = client.deploy(config.bpmn_path, deployment_name=config.deployment_name)
        print(f"  Deployed '{deployment.get('name')}' (id={deployment.get('id')})")


def initiate(config: RunnerConfig, client: Client) -> str:
    print(f"Starting process '{config.process_key}' …")
    instance_id = client.start_process(config.process_key, config.variables)
    print(f"  Instance ID: {instance_id}")
    return instance_id


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)

    cfg = RunnerConfig.from_file(args.config)
    client = Client(
        base_url=cfg.fluxnova_url,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )

    deploy(config=cfg, client=client, skip=args.skip_deploy)

    if args.with_mock_workers:
        from fluxnova_runner import mock_workers as _mw

        _mw.start_workers(
            cfg,
            username=os.environ.get("FLUXNOVA_USERNAME"),
            password=os.environ.get("FLUXNOVA_PASSWORD"),
        )

    instance_id = initiate(config=cfg, client=client)

    if args.wait_for_activity:
        print(f"Waiting for activity '{args.wait_for_activity}' to complete …")
        client.wait_for_activity_completion(instance_id, args.wait_for_activity)
        print(f"Activity '{args.wait_for_activity}' on {instance_id} completed.")
    else:
        print("Waiting for process to complete …")
        client.wait_for_completion(instance_id)
        print(f"Process {instance_id} completed.")
    print(
        "Run 'mlflow-eval <config> --collect' to record the completed subprocess run "
        "into the MLflow evaluation dataset."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
