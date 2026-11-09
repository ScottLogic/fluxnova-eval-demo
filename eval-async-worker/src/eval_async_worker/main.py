"""CLI entry point for the eval-async-worker.

Usage
-----
    eval-async-worker --config config.yaml
    eval-async-worker --config config.yaml --fluxnova-url http://fluxnova-local:8080/engine-rest

Static settings come from the YAML ``--config`` file (see ``config.yaml`` /
``eval_async_worker.config``). Every setting can also be overridden by a
``EVAL_ASYNC_<NAME>`` environment variable or a CLI flag — flags win over
env vars, which win over the file, which wins over the built-in defaults — so
container deployments can point at pod-name-based URLs without editing the file
(see local-dev/services/eval-async-up.sh).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Iterable
from typing import Any

from fluxnova_mlflow_dataset import FluxnovaClient

from eval_async_worker.config import AsyncWorkerConfig
from eval_async_worker.control import SampleRateControl, start_control_server
from eval_async_worker.worker import AsyncEvalWorker

# (CLI flag dest / env suffix, config attribute, type)
_OVERRIDES: list[tuple[str, str, Callable[[str], Any]]] = [
    ("fluxnova_url", "fluxnova_url", lambda v: v.rstrip("/")),
    ("topic", "topic", str),
    ("lock_duration_ms", "lock_duration_ms", int),
    ("tracking_uri", "tracking_uri", lambda v: v.rstrip("/")),
    ("experiment_name", "experiment_name", str),
    ("trace_poll_timeout", "trace_poll_timeout_s", float),
    ("trace_poll_interval", "trace_poll_interval_s", float),
    ("sample_rate", "sample_rate", float),
    ("control_host", "control_host", str),
    ("control_port", "control_port", int),
]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"EVAL_ASYNC_{name}", default)


def _build_config(args: argparse.Namespace) -> AsyncWorkerConfig:
    """Layer overrides on top of the file/defaults: CLI flag > env var > file > default."""
    config = AsyncWorkerConfig.from_file(args.config) if args.config else AsyncWorkerConfig()
    for dest, attr, convert in _OVERRIDES:
        raw = getattr(args, dest) or _env(dest.upper())
        if raw:
            setattr(config, attr, convert(raw))
    return config


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the non-blocking Eval service task (agent-output-eval-async): score "
        "each agent run with the shared scorers and record the results in MLflow. Every flag can "
        "also be set via an EVAL_ASYNC_<NAME> environment variable (e.g. "
        "EVAL_ASYNC_FLUXNOVA_URL)."
    )
    parser.add_argument(
        "--config",
        default=_env("CONFIG"),
        help="Path to the YAML config file (see config.yaml). Optional — built-in defaults "
        "are used if omitted.",
    )
    parser.add_argument("--fluxnova-url", default=None, help="Fluxnova engine REST base URL.")
    parser.add_argument("--topic", default=None, help="External-task topic to serve.")
    parser.add_argument("--lock-duration-ms", default=None, help="External-task lock duration.")
    parser.add_argument("--tracking-uri", default=None, help="MLflow tracking server URL.")
    parser.add_argument("--experiment-name", default=None, help="MLflow experiment of the traces.")
    parser.add_argument(
        "--trace-poll-timeout", default=None, help="Max seconds to wait for the run's trace."
    )
    parser.add_argument(
        "--trace-poll-interval", default=None, help="Seconds between trace lookups."
    )
    parser.add_argument(
        "--sample-rate",
        default=None,
        help="Fraction of async Eval tasks to score, 0.0-1.0 (default: 1.0). Unsampled tasks are "
        "completed without scoring. Can also be changed live via PUT "
        "http://<host>:<control-port>/config.",
    )
    parser.add_argument("--control-host", default=None, help="Control endpoint bind host.")
    parser.add_argument("--control-port", default=None, help="Control endpoint port.")
    parser.add_argument("--log-level", default=_env("LOG_LEVEL", "INFO"), help="Logging level.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = _build_config(args)
    username = os.environ.get("FLUXNOVA_USERNAME")
    password = os.environ.get("FLUXNOVA_PASSWORD")
    sample_rate = SampleRateControl(config.sample_rate)
    start_control_server(sample_rate, config.control_host, config.control_port)
    client = FluxnovaClient(config.fluxnova_url, username=username, password=password)
    AsyncEvalWorker(config, client=client, sample_rate=sample_rate).run_forever(
        username=username, password=password
    )


if __name__ == "__main__":
    main(sys.argv[1:])
