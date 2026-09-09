# regression

The end-to-end **MLflow agent regression suite** for the Fluxnova loan-assessment agent — the project's gating check
against behavioural regressions. It lives at the repo root (rather than inside any one package) because it drives the
whole stack: it depends on `fluxnova-runner` (to run the live agent) and `fluxnova-mlflow-dataset` (for the shared
judges/scorers), not on the `harness` package's own source.

## What it does

`test_mlflow_regression.py` follows MLflow's
[regression-testing pattern](https://mlflow.org/docs/latest/genai/eval-monitor/regression-testing/): for every golden
scenario in [`datasets/loan-assessment/goldens.json`](../datasets/loan-assessment/goldens.json) it drives the live
loan-assessment agent end-to-end via `fluxnova-runner`, then scores the agent's *actual* output. Two gating tests:

- `test_agent_reaches_evidence_backed_decision` — the output satisfies the shared `decision_quality` guideline judge
  (a definitive APPROVE/REJECT backed by cited evidence).
- `test_agent_matches_golden_decisions` — the output matches the golden's `expected_output` via the shared
  `matches_golden` judge (thresholded at `GOLDEN_MATCH_THRESHOLD`).

Unlike `mlflow-eval` (which re-scores already-recorded runs), this actually runs the agent. It's a gating check, not a
coverage suite. Results are recorded to the shared PostgreSQL-backed MLflow tracking store under a dedicated
`fluxnova-loanAssessmentProcess-regression` experiment (kept separate from real recorded agent runs).

## Running

From the repo root, with the shared `.venv` active (see the root [README](../README.md#first-time-setup)):

```bash
pytest regression -v
# or a single test:
pytest regression/test_mlflow_regression.py -v
```

**Prerequisites:** the full live stack must be up (Fluxnova engine, Postgres, OTel Collector, MLflow, Ollama — see
[`local-dev/README.md`](../local-dev/README.md)). The suite **skips cleanly** if the engine or tracking store isn't
reachable rather than failing.

## Configuration

- `pytest.ini` here enables MLflow's pytest plugin (`-p mlflow.pytest.plugin`) and live console logging.
- `conftest.py` points `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME` at the shared store + regression experiment
  before any run opens, caps noisy third-party loggers, and serialises judge calls (`MLFLOW_GENAI_EVAL_MAX_WORKERS=1`).

### Environment variables

All are optional — each has a working default. `setdefault` semantics mean an externally-provided value (e.g. from CI)
is always respected.

| Variable                            | Default                                            | Set in                                        | Purpose                                                                 |
|-------------------------------------|----------------------------------------------------|-----------------------------------------------|------------------------------------------------------------------------|
| `REGRESSION_ACTIVITY_TIMEOUT`       | `600` (seconds)                                    | `test_mlflow_regression.py`                   | Max time to wait for one golden's agentic subprocess run to finish     |
| `REGRESSION_GOLDEN_MATCH_THRESHOLD` | `0.7`                                              | `fluxnova_mlflow_dataset.scorers`             | Min `matches_golden` judge score (0.0–1.0) counted as a "yes" verdict  |
| `MLFLOW_GENAI_EVAL_MAX_WORKERS`     | `1` (this suite; MLflow's own default is `10`)     | `conftest.py`                                 | Judge-call concurrency; capped to 1 so the local CPU Ollama judge copes |
| `MLFLOW_TRACKING_URI`               | shared Postgres store (`default_tracking_uri`)     | `conftest.py`                                 | Where runs/assessments are recorded                                    |
| `MLFLOW_EXPERIMENT_NAME`            | `fluxnova-loanAssessmentProcess-regression`        | `conftest.py`                                 | Experiment the regression runs land in                                |
| `FLUXNOVA_USERNAME` / `FLUXNOVA_PASSWORD` | none                                         | read by `test_mlflow_regression.py`           | Credentials for the Fluxnova engine / mock workers                    |

> **Note:** `REGRESSION_GOLDEN_MATCH_THRESHOLD` is read inside the shared `fluxnova-mlflow-dataset` package (the
> `matches_golden` scorer), not in this directory — it keeps the `REGRESSION_` prefix so all knobs for a regression run
> are discoverable by name.
