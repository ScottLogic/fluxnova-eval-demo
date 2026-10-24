"""Create/resolve the trace experiment and atomically write collector headers.

Uses only the standard library, so the same script works in the MLflow image
and as a host CLI. Run before starting the collector; no fixed experiment ID.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(base_url: str, path: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)


def ensure_experiment(base_url: str, name: str) -> str:
    path = "/api/2.0/mlflow/experiments/get-by-name?" + urllib.parse.urlencode(
        {"experiment_name": name}
    )
    try:
        experiment = request(base_url, path)["experiment"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        return str(
            request(base_url, "/api/2.0/mlflow/experiments/create", {"name": name})[
                "experiment_id"
            ]
        )
    if experiment.get("lifecycle_stage") == "deleted":
        raise ValueError(f"Experiment {name!r} is deleted; restore it in MLflow first.")
    location = experiment.get("artifact_location", "")
    scheme = urllib.parse.urlparse(location).scheme
    if scheme in ("", "file") or len(scheme) == 1:
        raise ValueError(
            f"Experiment {name!r} uses container-local artifact storage {location!r}. "
            "Set EVAL_SERVICE_EXPERIMENT_NAME to a fresh name (for example with '-v2') "
            "and recreate the stack. Existing experiments and files are preserved."
        )
    return str(experiment["experiment_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri",
        default=f"http://localhost:{os.environ.get('MLFLOW_PORT', '5001')}",
    )
    parser.add_argument(
        "--experiment-name", default="fluxnova-loanAssessmentEvalProcess"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            experiment_id = ensure_experiment(args.tracking_uri, args.experiment_name)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            # Retry transient server startup errors, but fail on invalid requests/auth.
            if isinstance(error, urllib.error.HTTPError) and error.code < 500:
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "MLflow did not become ready for experiment initialization"
                ) from error
            time.sleep(2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        # JSON is valid YAML; quoting the ID ensures an HTTP string header.
        temporary.write_text(
            json.dumps({"x-mlflow-experiment-id": experiment_id}) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, args.output)
    print(experiment_id)


if __name__ == "__main__":
    main()
