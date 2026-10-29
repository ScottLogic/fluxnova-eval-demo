import json

import pandas as pd
import pytest

from regression.reporting import build_report, failure_message, write_report


def _case(name="example", collateral=False):
    return {"inputs": {"scenario": name, "process_instance_id": f"process-{name}",
                       "input_variables": {"applicantType": "EMPLOYED", "hasCollateral": collateral},
                       "iterations": 4, "tool_calls": []},
            "expectations": {"expected_output": "APPROVE"}}


def test_all_failures_include_scenario_process_and_rationale(tmp_path):
    expected = [_case("first"), _case("second")]
    table = pd.DataFrame([
        {"inputs": c["inputs"], "outputs": "APPROVE", "decision_quality/value": "no",
         "decision_quality/rationale": "Missing evidence", "step_efficiency/value": False,
         "step_efficiency/rationale": "Too many calls"} for c in reversed(expected)
    ])
    report = build_report(table, expected, ["decision_quality", "step_efficiency"], "all")
    assert len(report["failures"]) == 4
    message = failure_message(report)
    assert "first" in message and "process-second" in message and "Missing evidence" in message
    assert report["cases"][0]["scenario"] == "first"  # join by identity, not result order
    write_report(report, tmp_path / "report.json")
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved["cases"][0]["outputs"] == "APPROVE"
    assert saved["cases"][0]["inputs"]["iterations"] == 4


@pytest.mark.parametrize("row", [{}, {"score/value": None}, {"score/value": float("nan")},
                                 {"score/value": True, "score/error_message": "provider failure"}])
def test_missing_or_errored_verdict_cannot_pass(row):
    case = _case()
    table = pd.DataFrame([{"inputs": case["inputs"], **row}])
    assert build_report(table, [case], ["score"], "gate")["failures"]


def test_intentional_profile_skip_is_preserved_but_error_is_not():
    case = _case(collateral=True)
    name = "no_collateral_check_when_no_collateral"
    table = pd.DataFrame([{"inputs": case["inputs"], f"{name}/value": None}])
    assert not build_report(table, [case], [name], "gate")["failures"]
    table[f"{name}/error_message"] = "scorer crashed"
    assert build_report(table, [case], [name], "gate")["failures"]


def test_missing_result_and_duplicate_result_fail_closed():
    case = _case()
    assert build_report(pd.DataFrame(), [case], ["score"], "gate")["failures"]
    row = {"inputs": case["inputs"], "score/value": True}
    assert build_report(pd.DataFrame([row, row]), [case], ["score"], "gate")["failures"]


def test_numeric_thresholds_and_non_finite_values():
    case = _case()
    for value, passed in [(0.8, True), (0.6, False), (float("inf"), False)]:
        table = pd.DataFrame([{"inputs": case["inputs"], "score/value": value}])
        report = build_report(table, [case], ["score"], "gate", {"score": 0.7})
        assert bool(report["failures"]) != passed
        json.dumps(report, allow_nan=False)


def test_public_mlflow_trace_table_retains_kwargs_identity_and_assessment_rationale():
    case = _case()
    table = pd.DataFrame([{
        "request": {"input_variables": case["inputs"]["input_variables"],
                    "_scorer_only_fields": {k: v for k, v in case["inputs"].items() if k != "input_variables"}},
        "response": "Evidence.\nAPPROVE", "score/value": False,
        "assessments": [{"assessment_name": "score", "feedback": {"value": False},
                         "rationale": "Specific failing reason", "valid": True}],
    }])
    report = build_report(table, [case], ["score"], "gate")
    assert len(report["failures"]) == 1
    assert report["failures"][0]["rationale"] == "Specific failing reason"
    assert report["cases"][0]["outputs"] == "Evidence.\nAPPROVE"


def test_parametrized_reports_preserve_each_scenario_in_one_mlflow_run(tmp_path, monkeypatch):
    import runpy
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import Mock

    import mlflow

    module = runpy.run_path(str(Path(__file__).parents[2] / "regression/test_mlflow_regression.py"))
    log = Mock()
    monkeypatch.setattr(mlflow, "log_dict", log)
    monkeypatch.setenv("REGRESSION_REPORT_DIR", str(tmp_path))
    for name in ("first", "second"):
        case = _case(name)
        table = pd.DataFrame([{"request": case["inputs"], "response": "Evidence.\nAPPROVE",
                               "assessments": [{"assessment_name": "score", "feedback": {"value": True}}]}])
        result = SimpleNamespace(run_id="shared-run", tables={"eval_results": table})
        module["_report_gate"](result, [case], ["score"], "deterministic", scenario=name)
    assert {call.args[1] for call in log.call_args_list} == {
        "regression/first/deterministic.json", "regression/second/deterministic.json"}
    assert json.loads((tmp_path / "shared-run/first/deterministic.json").read_text())["cases"][0]["scenario"] == "first"
    assert (tmp_path / "shared-run/second/deterministic.json").is_file()
