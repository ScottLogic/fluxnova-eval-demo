"""CLI entry point for the eval-trace-listener.

Usage
-----
    eval-trace-listener --config config.yaml
    eval-trace-listener --config config.yaml --tracking-uri http://mlflow-local:5000

Static settings come from the YAML ``--config`` file (see ``config.yaml`` /
``eval_trace_listener.config``). Every setting can also be overridden by a
``EVAL_LISTENER_<NAME>`` environment variable or a CLI flag — flags win over
env vars, which win over the file, which wins over the built-in defaults — so
container deployments can point at pod-name-based URLs without editing the file
(see local-dev/services/eval-listener-up.sh).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable

from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.listener import TraceListener


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"EVAL_LISTENER_{name}", default)


def _build_config(args: argparse.Namespace) -> ListenerConfig:
    """Layer overrides on top of the file/defaults: CLI flag > env var > file > default."""
    config = ListenerConfig.from_file(args.config) if args.config else ListenerConfig()

    tracking_uri = args.tracking_uri or _env("TRACKING_URI")
    if tracking_uri:
        config.tracking_uri = tracking_uri.rstrip("/")

    experiment_name = args.experiment_name or _env("EXPERIMENT_NAME")
    if experiment_name:
        config.experiment_name = experiment_name

    if args.agent_name:
        config.agent_names = list(args.agent_name)
    elif _env("AGENT_NAMES"):
        config.agent_names = [a.strip() for a in _env("AGENT_NAMES").split(",") if a.strip()]

    poll_interval = args.poll_interval or _env("POLL_INTERVAL_S")
    if poll_interval:
        config.poll_interval_s = float(poll_interval)

    return config


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tail an MLflow experiment's trace store and score completed agent runs "
        "with the deterministic (trace-only) scorers. Every flag can also be set via an "
        "EVAL_LISTENER_<NAME> environment variable (e.g. EVAL_LISTENER_TRACKING_URI)."
    )
    parser.add_argument(
        "--config",
        default=_env("CONFIG"),
        help="Path to the YAML config file (see config.yaml). Optional — built-in defaults "
        "are used if omitted.",
    )
    parser.add_argument("--tracking-uri", default=None, help="Override MLflow tracking server URL.")
    parser.add_argument("--experiment-name", default=None, help="Override the experiment to tail.")
    parser.add_argument(
        "--agent-name",
        action="append",
        default=None,
        help="Only score runs of this agent (gen_ai.agent.name). Repeatable. Overrides the "
        "config file's agent_names.",
    )
    parser.add_argument("--poll-interval", default=None, help="Override the poll interval (seconds).")
    parser.add_argument("--log-level", default=_env("LOG_LEVEL", "INFO"), help="Logging level (default: INFO).")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = _build_config(args)
    TraceListener(config).run_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
