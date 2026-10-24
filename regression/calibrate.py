"""Judge frozen examples or replay a regression report without executing the agent."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from regression.reporting import build_report, failure_message, write_report

DEFAULT_CASES = Path(__file__).parent / "calibration/decision_quality.json"


def load_cases(path: Path, *, report: bool = False) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"] if report else payload
    if not cases or not isinstance(cases, list):
        raise ValueError("Calibration/replay requires a non-empty list of frozen cases")
    names = set()
    normalized = []
    for case in cases:
        name = case["scenario"]
        if name in names or not isinstance(case.get("outputs"), str) or not case["outputs"].strip():
            raise ValueError(f"Duplicate scenario or missing frozen output: {name!r}")
        names.add(name)
        verdict = case.get("expected_verdict", "yes")
        if verdict not in {"yes", "no"}:
            raise ValueError(f"Invalid expected verdict for {name!r}: {verdict!r}")
        normalized.append({**case, "expected_verdict": verdict, "inputs": {
            **case.get("inputs", {}), "scenario": name,
            "process_instance_id": case.get("process_instance_id") or case.get("inputs", {}).get("process_instance_id") or f"frozen-{name}",
        }})
    return normalized


def judge_report(table, cases: list[dict], name: str) -> dict:
    report = build_report(table, cases, [name], "decision-quality-calibration")
    # In calibration a deliberately bad response should receive 'no'. Preserve
    # structural errors from the common reporter, then compare the labeled verdicts.
    failures = [failure for failure in report["failures"] if failure["scorer"] == "evaluation"]
    expected = {case["scenario"]: case["expected_verdict"] for case in cases}
    for case in report["cases"]:
        assessment = case["scorers"][name]
        wanted = expected[case["scenario"]]
        case["expected_verdict"] = wanted
        passed = not assessment["error"] and assessment["value"] == wanted
        assessment["status"] = "passed" if passed else "failed"
        if not passed:
            failures.append({"scenario": case["scenario"], "scorer": name, **assessment,
                             "error": assessment["error"] or f"Expected {wanted!r}, got {assessment['value']!r}: {assessment['rationale']}"})
    report["failures"] = failures
    return report


def deterministic_replay(cases: list[dict]) -> dict:
    import pandas as pd
    from fluxnova_mlflow_dataset.scorers import ALL_DETERMINISTIC_SCORERS

    rows = []
    for case in cases:
        row = {"inputs": case["inputs"], "outputs": case["outputs"]}
        for scorer in ALL_DETERMINISTIC_SCORERS:
            try:
                feedback = scorer.run(inputs=case["inputs"], outputs=case["outputs"])
                if feedback is not None:
                    row[f"{scorer.name}/value"] = feedback.value
                    row[f"{scorer.name}/rationale"] = feedback.rationale
                    row[f"{scorer.name}/error_message"] = feedback.error_message
            except Exception as error:  # noqa: BLE001 - aggregate scorer errors as failed verdicts
                row[f"{scorer.name}/error_message"] = str(error)
        rows.append(row)
    return build_report(pd.DataFrame(rows), cases, [s.name for s in ALL_DETERMINISTIC_SCORERS], "deterministic-replay")


def run_judge(cases: list[dict], tracking_uri: str, experiment_name: str, model: str | None = None) -> dict:
    import mlflow
    from fluxnova_mlflow_dataset.experiments import require_remote_artifacts
    from fluxnova_mlflow_dataset.scorers import (
        DECISION_QUALITY_RUBRIC_VERSION,
        decision_quality,
        decision_quality_judge,
    )

    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name)
    require_remote_artifacts(experiment)
    judge = decision_quality_judge(model or decision_quality.model)
    with mlflow.start_run(experiment_id=experiment.experiment_id, run_name="decision-quality-calibration") as run:
        mlflow.set_tags({"judge_rubric_version": DECISION_QUALITY_RUBRIC_VERSION, "judge_model": judge.model})
        data = [{"inputs": case["inputs"], "outputs": case["outputs"]} for case in cases]
        result = mlflow.genai.evaluate(data=data, scorers=[judge])
        report = judge_report(result.tables["eval_results"], cases, judge.name)
        report.update(run_id=run.info.run_id, model=judge.model, rubric_version=DECISION_QUALITY_RUBRIC_VERSION)
        mlflow.log_dict(report, "calibration/decision_quality.json")
    return report


def main(argv=None) -> int:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[1] / "local-dev/.env")
    from fluxnova_mlflow_dataset.store import default_server_tracking_uri

    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    source.add_argument("--report", type=Path, help="Replay a saved regression JSON report; all outputs are expected to pass judging")
    parser.add_argument("--mode", choices=["judge", "deterministic"], default="judge")
    parser.add_argument("--tracking-uri", default=default_server_tracking_uri())
    parser.add_argument("--experiment-name", default="fluxnova-decision-quality-calibration-v2")
    parser.add_argument("--model", help="MLflow model URI for an explicit judge candidate")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "deterministic" and args.report is None:
        parser.error("--mode deterministic requires --report with captured tool calls and iterations")
    cases = load_cases(args.report or args.cases, report=args.report is not None)
    report = (deterministic_replay(cases) if args.mode == "deterministic" else
              run_judge(cases, args.tracking_uri, args.experiment_name, args.model))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or Path(__file__).parents[1] / f"local-dev/.mlflow/calibration/{stamp}-{args.mode}.json"
    write_report(report, output)
    print(f"{len(report['cases'])} frozen cases; {len(report['failures'])} failures; report: {output}")
    if report["failures"]:
        print(failure_message(report))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
