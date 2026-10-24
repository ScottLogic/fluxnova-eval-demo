from types import SimpleNamespace

import pytest

from fluxnova_mlflow_dataset.experiments import require_remote_artifacts


@pytest.mark.parametrize("location", ["/mlflow-artifacts/2", "file:///mlflow-artifacts/2", "C:\\artifacts\\2", ""])
def test_local_artifacts_are_rejected_with_migration_guidance(location):
    with pytest.raises(ValueError, match="fresh experiment"):
        require_remote_artifacts(SimpleNamespace(name="old", artifact_location=location))


@pytest.mark.parametrize("location", ["mlflow-artifacts:/2", "https://tracking.example/artifacts/2", "s3://bucket/2"])
def test_remote_artifacts_are_accepted(location):
    require_remote_artifacts(SimpleNamespace(name="new", artifact_location=location))
