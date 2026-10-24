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
