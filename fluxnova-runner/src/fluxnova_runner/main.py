"""Entry point for the standalone Fluxnova automated-run service.

Reads a YAML config file, deploys the specified BPMN to Fluxnova, optionally
starts mock external-task workers, starts a process instance, and polls
until it completes. Reporting/evaluation is *not* this service's job — the
``eval-trace-listener`` service tails MLflow's trace store and scores each
completed run automatically (or use ``eval-service-worker`` for synchronous
per-run scoring). The run's trace is already persisted in MLflow by the time
this service returns.

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
            "block this run from being considered done. Overrides the config file's "
            "'wait_for_activity' field when both are given."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        metavar="SECONDS",
        help=(
            "Maximum seconds to wait for the process (or --wait-for-activity "
            "activity) to complete before raising a TimeoutError. Raise this for "
            "slower CPU-only local models (default: 600)."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def deploy(config: RunnerConfig, client: Client, skip: bool) -> None:
    if not skip:
        print(f"Deploying {config.bpmn_path} …")
        for extra in config.additional_bpmn_paths:
            print(f"  + additional resource {extra}")
        deployment = client.deploy(
            config.bpmn_path,
            deployment_name=config.deployment_name,
            additional_paths=config.additional_bpmn_paths,
        )
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

    # CLI flag takes precedence; otherwise fall back to the config file's field.
    wait_for_activity = args.wait_for_activity or cfg.wait_for_activity

    if wait_for_activity:
        print(f"Waiting for activity '{wait_for_activity}' to complete …")
        client.wait_for_activity_completion(
            instance_id, wait_for_activity, timeout=args.timeout
        )
        print(f"Activity '{wait_for_activity}' on {instance_id} completed.")
    else:
        print("Waiting for process to complete …")
        client.wait_for_completion(instance_id, timeout=args.timeout)
        print(f"Process {instance_id} completed.")
    print(
        "The completed subprocess run's trace is persisted in MLflow; the "
        "eval-trace-listener service (if running) will score it automatically."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
