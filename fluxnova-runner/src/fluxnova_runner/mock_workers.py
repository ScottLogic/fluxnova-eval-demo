"""Mock external task workers driven by a workflow YAML config.

Subscribes to every topic listed under ``mock_workers`` in the config file and
immediately completes each task with the configured output variables.

Usage
-----
    fluxnova-run-mock-workers fluxnova-runner/config/loan-assesment.yml
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from camunda.external_task.external_task import ExternalTask
from camunda.external_task.external_task_worker import ExternalTaskWorker

from fluxnova_runner.config import RunnerConfig

logger = logging.getLogger(__name__)

# Prefix for per-instance mock-output overrides. When a process instance is
# started with a variable named ``_mock_output_<outputKey>`` (e.g.
# ``_mock_output_fraudRiskScore``), the matching mock worker completes its task
# with that value instead of the static default from the config. This lets a
# single, long-lived worker pool replay different scenarios (e.g. one golden per
# process instance) without restarting workers — the per-scenario data rides
# along inside each instance's own variables. Absent the override, the config
# default is used, so the normal single-run path
# (``fluxnova-run-mock-workers config/...yml``) is unaffected.
_MOCK_VAR_PREFIX = "_mock_output_"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_camunda_vars(variables: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _type_map = {str: "String", int: "Integer", float: "Double", bool: "Boolean"}
    return {
        name: {"value": value, "type": _type_map.get(type(value), "String")}
        for name, value in variables.items()
    }


def _resolve_outputs(task: ExternalTask, outputs: dict[str, Any]) -> dict[str, Any]:
    """Return the task's output vars, overriding each key from a matching
    ``_mock_output_<key>`` instance variable when the running instance provides one.
    """
    resolved: dict[str, Any] = {}
    for key, default in outputs.items():
        override = task.get_variable(f"{_MOCK_VAR_PREFIX}{key}")
        resolved[key] = default if override is None else override
    return resolved


def _make_handler(topic: str, outputs: dict[str, Any]):
    def handle(task: ExternalTask):
        print(f"[{_now()}] LOCKED  topic={topic} taskId={task.get_task_id()}")
        resolved = _resolve_outputs(task, outputs)
        # Jitter before completing to avoid OptimisticLockingException when
        # multiple parallel tasks in the same ad-hoc subprocess complete
        # simultaneously and race to update the same execution entity.
        time.sleep(random.uniform(0.0, 0.5))
        result = task.complete(global_variables=_to_camunda_vars(resolved))
        print(f"[{_now()}] DONE    topic={topic} outputs={resolved}")
        return result

    return handle


def start_workers(
    cfg: RunnerConfig, username: str | None = None, password: str | None = None
) -> list[threading.Thread]:
    """Start one worker daemon thread per topic and return the threads (non-blocking).

    Worker threads are daemons — they will be cleaned up automatically when the
    main thread exits.  Call :func:`run` instead if you want to block until
    interrupted.
    """
    if not cfg.mock_workers:
        print("No mock_workers defined in config — nothing to start.")
        return []

    worker_config: dict[str, Any] = {
        "maxTasks": 1,
        "lockDuration": 10_000,
        "asyncResponseTimeout": 10_000,
        "retries": 3,
        "retryTimeout": 5_000,
        "sleepSeconds": 2,
    }
    if username or password:
        worker_config["auth_basic"] = {"username": username or "", "password": password or ""}

    threads: list[threading.Thread] = []
    for i, (topic, outputs) in enumerate(cfg.mock_workers.items()):
        worker = ExternalTaskWorker(
            worker_id=str(i),
            base_url=cfg.fluxnova_url,
            config=worker_config,
        )
        t = threading.Thread(
            target=worker.subscribe,
            args=([topic], _make_handler(topic, outputs or {})),
            daemon=True,
            name=f"worker-{topic}",
        )
        threads.append(t)

    for t in threads:
        t.start()

    print(f"Mock workers running. Topics: {', '.join(cfg.mock_workers)}")
    return threads


def run(cfg: RunnerConfig, username: str | None = None, password: str | None = None) -> None:
    """Start one worker thread per topic and block until interrupted."""
    threads = start_workers(cfg, username=username, password=password)
    if not threads:
        return

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nShutting down mock workers.")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mock external task workers for a Fluxnova workflow")
    parser.add_argument("config", type=Path, help="Path to the workflow YAML config file")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = RunnerConfig.from_file(args.config)
    run(
        cfg,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )


if __name__ == "__main__":
    main(sys.argv[1:])
