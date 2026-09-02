"""MLflow regression test (see
https://mlflow.org/docs/latest/genai/eval-monitor/regression-testing/) for the
Fluxnova loan-assessment agent.

Unlike ``mlflow_eval``'s offline batch evaluation (which measures aggregate
scores across every *recorded* run) or ``deep_eval`` (DEPRECATED), this is a
gating check: it runs the shared ``decision_quality`` guideline judge (see
``fluxnova_mlflow_dataset.scorers``) against the curated known-good reference
answers in the golden dataset (``datasets/loan-assessment/goldens.json``) and
asserts every one still satisfies the guidelines. If a future change to the
``decision_quality`` guideline text stops matching what we already know is a
good answer, this test fails immediately instead of silently drifting.

Results are recorded to the same shared PostgreSQL-backed MLflow tracking store
used by the rest of the project (see ``local-dev/postgres-up.sh``), under a
dedicated ``fluxnova-loanAssessmentProcess-regression`` experiment so runs
don't mix with real recorded agent runs.

Run with:
    pytest harness/tests/test_mlflow_regression.py -v
"""

from __future__ import annotations

from pathlib import Path

import mlflow
from fluxnova_mlflow_dataset import decision_quality, default_tracking_uri, experiment_name_for
from fluxnova_mlflow_dataset.goldens import load_goldens

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GOLDENS_PATH = _REPO_ROOT / "datasets" / "loan-assessment" / "goldens.json"

# Recorded under a dedicated experiment (not the live "fluxnova-loanAssessmentProcess"
# experiment used for real recorded runs) so regression-test runs don't clutter it.
_EXPERIMENT_NAME = experiment_name_for("loanAssessmentProcess-regression")


@mlflow.test
def test_golden_outputs_satisfy_decision_quality() -> None:
    """Every golden reference answer must satisfy the ``decision_quality`` guidelines.

    Each golden's ``expected_output`` is treated as the agent's ``outputs`` for
    scoring purposes — there's no live agent run involved, just a check that
    our own known-good reference answers still pass the guideline judge.
    """
    mlflow.set_tracking_uri(default_tracking_uri(_REPO_ROOT))
    mlflow.set_experiment(_EXPERIMENT_NAME)

    goldens = load_goldens(_GOLDENS_PATH)
    assert goldens, f"No goldens found at {_GOLDENS_PATH}"

    data = [
        {
            "inputs": {"question": golden["input"]},
            "outputs": golden["expected_output"],
        }
        for golden in goldens
    ]
    result = mlflow.genai.evaluate(data=data, scorers=[decision_quality])
    assert result.passed, result.reason
