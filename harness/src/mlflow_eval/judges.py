"""CLI to toggle MLflow *automatic* (online) evaluation judges on/off.

Automatic evaluation (``Scorer.register()`` + ``Scorer.start()``) runs
entirely inside the MLflow server itself, scoring new traces as they land —
no code needs to run continuously. This script is the "on/off switch" for
that: it registers the gateway-backed judges from ``mlflow_eval.main`` (see
``automatic_judges()``) against a target experiment, then starts or stops
automatic sampling for them.

Automatic judges require a `gateway:/<endpoint>` model URI (see Phase 0 in
EDD-AND-PRODUCTION-EVAL-ANALYSIS.md), which in turn requires the tracking URI
to be the *running MLflow server's* HTTP(S) address (e.g.
``http://localhost:5000``) rather than a direct ``sqlite:///...`` path — the
gateway routes judge calls through that server process. This is different
from ``mlflow-eval``'s default tracking URI (the local SQLite file used for
offline evaluation), even though, in local dev, both ultimately point at the
same underlying `harness/.mlflow/mlflow.db` file (`mlflow-up.sh` mounts it
into the server container).

Usage (see also local-dev/README.md):

    # Register + start automatic sampling for all judges in automatic_judges()
    mlflow-judges start --experiment fluxnova-loanAssessmentProcess --sample-rate 0.1

    # Stop automatic sampling (judges stay registered; can be re-started anytime)
    mlflow-judges stop --experiment fluxnova-loanAssessmentProcess

    # Show current registration/sampling state
    mlflow-judges status --experiment fluxnova-loanAssessmentProcess
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable

import mlflow
from mlflow.genai.scorers import ScorerSamplingConfig, get_scorer, list_scorers

from mlflow_eval.main import GATEWAY_JUDGE_MODEL, automatic_judges

_DEFAULT_TRACKING_URI = "http://localhost:5000"


def _resolve_experiment_id(experiment_name: str) -> str:
    experiment = mlflow.set_experiment(experiment_name)
    return experiment.experiment_id


def _cmd_start(args: argparse.Namespace) -> None:
    mlflow.set_tracking_uri(args.tracking_uri)
    experiment_id = _resolve_experiment_id(args.experiment)
    sampling_config = ScorerSamplingConfig(sample_rate=args.sample_rate, filter_string=args.filter_string)
    for judge in automatic_judges(model=args.model):
        # register() returns a *new* Scorer instance carrying server registration info --
        # start()/stop() must be called on that instance, not the original.
        registered = judge.register(experiment_id=experiment_id)
        registered.start(experiment_id=experiment_id, sampling_config=sampling_config)
        print(
            f"started: {judge.name!r} (model={args.model}, sample_rate={args.sample_rate}, "
            f"filter_string={args.filter_string!r}) on experiment {args.experiment!r}"
        )


def _cmd_stop(args: argparse.Namespace) -> None:
    mlflow.set_tracking_uri(args.tracking_uri)
    experiment_id = _resolve_experiment_id(args.experiment)
    for judge in automatic_judges(model=args.model):
        registered = get_scorer(name=judge.name, experiment_id=experiment_id)
        registered.stop(experiment_id=experiment_id)
        print(f"stopped: {judge.name!r} on experiment {args.experiment!r} (still registered -- restart anytime)")


def _cmd_status(args: argparse.Namespace) -> None:
    mlflow.set_tracking_uri(args.tracking_uri)
    experiment_id = _resolve_experiment_id(args.experiment)
    scorers = list_scorers(experiment_id=experiment_id)
    if not scorers:
        print(f"No scorers registered on experiment {args.experiment!r}.")
        return
    for s in scorers:
        if s.sample_rate:
            state = f"AUTOMATIC (sample_rate={s.sample_rate}, filter_string={s.filter_string!r})"
        else:
            state = "registered, not running automatically"
        print(f"{s.name!r}: {state}")


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--experiment",
        required=True,
        help="MLflow experiment name to target (e.g. fluxnova-loanAssessmentProcess).",
    )
    parser.add_argument(
        "--tracking-uri",
        default=_DEFAULT_TRACKING_URI,
        help=f"MLflow tracking server HTTP(S) URL (default: {_DEFAULT_TRACKING_URI}). "
        "Must be the running server's address, not a direct sqlite:/// path -- gateway-backed "
        "judges route through the server process.",
    )
    parser.add_argument(
        "--model",
        default=GATEWAY_JUDGE_MODEL,
        help=f"Gateway model URI for the judges (default: {GATEWAY_JUDGE_MODEL}).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Register and start automatic sampling for all judges.")
    start_parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.1,
        help="Fraction of traces to sample for scoring (default: 0.1).",
    )
    start_parser.add_argument(
        "--filter-string",
        default=None,
        help="Optional MLflow filter string to restrict which traces get scored.",
    )
    start_parser.set_defaults(func=_cmd_start)

    stop_parser = subparsers.add_parser("stop", help="Stop automatic sampling (judges remain registered).")
    stop_parser.set_defaults(func=_cmd_stop)

    status_parser = subparsers.add_parser("status", help="Show registered judges and their sampling state.")
    status_parser.set_defaults(func=_cmd_status)

    args = parser.parse_args(list(argv) if argv is not None else None)
    args.func(args)


if __name__ == "__main__":
    main()
