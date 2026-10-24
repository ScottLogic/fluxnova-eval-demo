# Validate the regression fixes

Tracked upstream: [artifact proxy #22](https://github.com/ScottLogic/fluxnova-eval-demo/issues/22),
[failure reports #24](https://github.com/ScottLogic/fluxnova-eval-demo/issues/24),
[efficiency #25](https://github.com/ScottLogic/fluxnova-eval-demo/issues/25), and
[judge calibration #23](https://github.com/ScottLogic/fluxnova-eval-demo/issues/23).

Use the repository root in each terminal. These steps preserve old experiments,
runs and artifact files. The full demo setup is in [RUNNING-MACOS.md](../RUNNING-MACOS.md).

## 1. Upgrade the experiment names and recreate services

Activate `.venv` and edit your existing `local-dev/.env`, keeping the API key:

```dotenv
MLFLOW_PORT=5001
EVAL_SERVICE_EXPERIMENT_NAME=fluxnova-loanAssessmentEvalProcess-v2
MLFLOW_EXPERIMENT_NAME=fluxnova-loanAssessmentProcess-regression-v2
```

Fresh names are necessary for experiments previously advertising `/mlflow-artifacts`.
Restarting MLflow does not change artifact locations already stored in PostgreSQL.

```bash
source .venv/bin/activate
set -a
source local-dev/.env
set +a
./local-dev/pods-down.sh
./local-dev/pods-up.sh postgres mlflow fluxnova
REBUILD=1 ./local-dev/pods-up.sh eval-service eval-listener observability
```

Normal teardown keeps data. The rebuild updates the shared scorers in both eval
containers. The regression fixture and runner redeploy the modified BPMN on execution.

## 2. Verify artifact proxying before model calls

```bash
python local-dev/mlflow/check_artifacts.py
```

Expected: successful upload/download and a `mlflow-artifacts:/...` run URI, not a
container-local path. The command creates one small smoke-test run. Existing legacy
experiments remain available for historical inspection. If an experiment is rejected
as local-path storage, select a fresh name rather than changing Mac filesystem permissions.

## 3. Run offline and isolated-server checks

```bash
python -m pytest fluxnova-runner/tests -q
python -m pytest fluxnova-mlflow-dataset/tests -q
python -m pytest eval-service-worker/tests -q
python -m pytest eval-trace-listener/tests -q
python -m pytest local-dev/tests -q
RUN_MLFLOW_PROXY_TEST=1 python -m pytest local-dev/tests/test_artifact_proxy.py -q
```

The final command starts a temporary isolated MLflow server, checks real HTTP
artifact/report transport, and shuts it down. It makes no model calls by default.
The regular local-dev suite intentionally skips this opt-in integration test.

## 4. Calibrate the judge with frozen examples

```bash
python -m regression.calibrate
```

This makes eight judge calls and no agent/workflow calls. Expected: eight cases,
zero failures: the four positive examples receive `yes`, and the four negative
examples receive `no`. Inspect verdicts and rationales in the printed local JSON
report and MLflow's `fluxnova-decision-quality-calibration-v2` experiment. Repeat
once to assess stability, retaining both reports. Do not accept an all-yes judge,
provider errors or missing verdicts as calibration success.

If the model misjudges a case, inspect the recorded rationale and input before
changing the rubric or selecting an explicit `--model` candidate. Offline unit tests
alone are not evidence that a particular model is calibrated.

## 5. Run all four live regression gates

Stop any separately running mock-worker terminal from the demo first, then run:

```bash
python -m pytest regression -v -rs
```

Expected: six live scenarios cached across four passing gates, no artifact-path
warnings and no skips. The `-v2` regression experiment should contain the run and
`regression/*.json` artifacts. Local copies are under
`local-dev/.mlflow/reports/<run-id>/`. Failures now identify every affected scenario,
engine process ID, scorer value/error and rationale, including errors from scorers
that previously came after the first failed deterministic check.

Inspect actual tool batches and counts: normally at most four total LLM calls,
including the final response; at most five with a separate collateral phase.
Affordability must follow income verification. Five calls without collateral still
fail. New outputs must end with a plain `APPROVE` or `REJECT` line after an
evidence-linked justification.

## 6. Verify report replay and online scoring

Substitute the run ID printed by the regression:

```bash
python -m regression.calibrate --mode deterministic --report local-dev/.mlflow/reports/<run-id>/deterministic.json
python -m regression.calibrate --report local-dev/.mlflow/reports/<run-id>/decision_quality.json
```

The first command is offline; the second rejudges six frozen outputs. Neither
executes the agent. Their reports should preserve scenario/process identity and
explain any divergence. Old inefficient outputs should still fail current budgets.

Run the basic workflow and eval workflow from the Mac guide, using persistent mock
workers for the latter. Check trace payloads and assessments, `evalPassed` /
`evalRationale`, and the dashboard. No host or sibling-container client should try
to write directly to `/mlflow-artifacts`.

## 7. Record results for the future upstream PR

Record model/rubric versions, calibration report paths, regression run ID, counts,
artifact smoke result and online workflow results. Keep the old failed run for
comparison. The future PR against ScottLogic should include:

```text
Closes #22
Closes #24
Closes #25
Closes #23
```
