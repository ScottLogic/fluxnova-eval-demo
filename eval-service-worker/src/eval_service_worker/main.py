"""CLI entry point for the eval-service-worker.

Usage
-----
    eval-service-worker
    eval-service-worker --fluxnova-url http://fluxnova-local:8080/engine-rest \\
        --tracking-uri http://mlflow-local:5000

All settings have sensible defaults (see ``config.py``) — flags/env vars only
need to be set to override them for a given environment (e.g. pod-name-based
URLs when running as a container — see local-dev/eval-service-up.sh).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable

from eval_service_worker.config import EvalServiceConfig
from eval_service_worker.worker import run


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"EVAL_SERVICE_{name}", default)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    defaults = EvalServiceConfig()
    parser = argparse.ArgumentParser(
        description="Run the eval-service-worker: scores completed agentic subprocess "
        "runs against the decision_quality MLflow judge. Every flag can also be set via "
        "an EVAL_SERVICE_<NAME> environment variable (e.g. EVAL_SERVICE_FLUXNOVA_URL)."
    )
    parser.add_argument(
        "--fluxnova-url",
        default=_env("FLUXNOVA_URL", defaults.fluxnova_url),
        help=f"Fluxnova engine REST base URL (default: {defaults.fluxnova_url})",
    )
    parser.add_argument(
        "--experiment-name",
        default=_env("EXPERIMENT_NAME", defaults.experiment_name),
        help=f"MLflow experiment to read/write (default: {defaults.experiment_name})",
    )
    parser.add_argument(
        "--process-key",
        default=_env("PROCESS_KEY", defaults.process_key),
        help=f"Process key used to tag dataset records (default: {defaults.process_key})",
    )
    parser.add_argument(
        "--topic",
        default=_env("TOPIC", defaults.topic),
        help=f"External-task topic to subscribe to (default: {defaults.topic})",
    )
    parser.add_argument(
        "--judge-model",
        default=_env("JUDGE_MODEL", defaults.judge_model),
        help=f"MLflow judge model URI (default: {defaults.judge_model})",
    )
    parser.add_argument(
        "--lock-duration-ms",
        type=int,
        default=int(_env("LOCK_DURATION_MS", str(defaults.lock_duration_ms))),
        help=f"External-task lock duration in ms (default: {defaults.lock_duration_ms})",
    )
    parser.add_argument(
        "--tracking-uri",
        default=_env("TRACKING_URI", defaults.tracking_uri),
        help=f"MLflow tracking server HTTP(S) URL (default: {defaults.tracking_uri})",
    )
    parser.add_argument(
        "--trace-poll-timeout",
        type=float,
        default=float(_env("TRACE_POLL_TIMEOUT", str(defaults.trace_poll_timeout))),
        help=(
            "Max seconds to retry looking up the run's trace in MLflow before "
            f"giving up (default: {defaults.trace_poll_timeout})"
        ),
    )
    parser.add_argument(
        "--trace-poll-interval",
        type=float,
        default=float(_env("TRACE_POLL_INTERVAL", str(defaults.trace_poll_interval))),
        help=f"Seconds between trace lookup retries (default: {defaults.trace_poll_interval})",
    )
    parser.add_argument(
        "--log-level",
        default=_env("LOG_LEVEL", "INFO"),
        help="Python logging level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = EvalServiceConfig(
        fluxnova_url=args.fluxnova_url,
        experiment_name=args.experiment_name,
        process_key=args.process_key,
        topic=args.topic,
        judge_model=args.judge_model,
        lock_duration_ms=args.lock_duration_ms,
        tracking_uri=args.tracking_uri,
        trace_poll_timeout=args.trace_poll_timeout,
        trace_poll_interval=args.trace_poll_interval,
    )
    run(
        config,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )


if __name__ == "__main__":
    main(sys.argv[1:])
