"""Round-trip a small artifact through the tracking server, without model calls."""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from fluxnova_mlflow_dataset.experiments import require_remote_artifacts
from fluxnova_mlflow_dataset.store import default_server_tracking_uri
from mlflow import MlflowClient


def check_artifacts(tracking_uri: str, experiment_name: str) -> str:
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment = client.get_experiment(client.create_experiment(experiment_name))
    require_remote_artifacts(experiment)
    run = client.create_run(experiment.experiment_id, run_name="artifact-proxy-smoke")
    try:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "artifact-proxy.txt"
            source.write_text("Artifact proxy round-trip OK\n", encoding="utf-8")
            client.log_artifact(run.info.run_id, str(source))
            destination = root / "download"
            destination.mkdir()
            downloaded = client.download_artifacts(run.info.run_id, source.name, str(destination))
            assert Path(downloaded).read_bytes() == source.read_bytes(), "Artifact contents changed"
        client.set_terminated(run.info.run_id, "FINISHED")
    except Exception:
        client.set_terminated(run.info.run_id, "FAILED")
        raise
    print(f"Artifact upload/download passed: {run.info.artifact_uri} (run {run.info.run_id})")
    return run.info.run_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", default=default_server_tracking_uri())
    parser.add_argument("--experiment-name", default="fluxnova-artifact-proxy-smoke")
    args = parser.parse_args()
    check_artifacts(args.tracking_uri, args.experiment_name)


if __name__ == "__main__":
    main()
