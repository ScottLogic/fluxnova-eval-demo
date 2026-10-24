import json
from pathlib import Path

import pandas as pd
import pytest
from fluxnova_mlflow_dataset.scorers import (
    DECISION_QUALITY_GUIDELINES,
    DECISION_QUALITY_RUBRIC_VERSION,
    decision_quality_judge,
    final_recommendation_format,
)

from regression.calibrate import (
    DEFAULT_CASES,
    deterministic_replay,
    judge_report,
    load_cases,
)


def test_frozen_suite_contains_valid_and_deliberately_bad_outputs():
    cases = load_cases(DEFAULT_CASES)
    assert len(cases) == 8
    assert {case["expected_verdict"] for case in cases} == {"yes", "no"}
    assert len({case["scenario"] for case in cases}) == len(cases)


def test_negative_examples_must_be_rejected_not_blindly_passed():
    cases = load_cases(DEFAULT_CASES)
    table = pd.DataFrame([{"inputs": c["inputs"], "outputs": c["outputs"],
                           "decision_quality/value": c["expected_verdict"]} for c in cases])
    assert not judge_report(table, cases, "decision_quality")["failures"]
    table["decision_quality/value"] = "yes"
    failures = judge_report(table, cases, "decision_quality")["failures"]
    assert len(failures) == 4 and all(f["scenario"].startswith("invalid-") for f in failures)


def test_judge_error_cannot_count_as_correct_rejection():
    case = load_cases(DEFAULT_CASES)[-1]
    table = pd.DataFrame([{"inputs": case["inputs"], "decision_quality/value": "no",
                           "decision_quality/error_message": "provider unavailable"}])
    assert judge_report(table, [case], "decision_quality")["failures"]


def test_current_rubric_is_wired_to_every_built_judge():
    judge = decision_quality_judge("openai:/gpt-4o-mini")
    assert judge.guidelines == DECISION_QUALITY_GUIDELINES
    assert DECISION_QUALITY_RUBRIC_VERSION == "2"
    assert "need not be repeated" in " ".join(judge.guidelines)


@pytest.mark.parametrize("output, expected", [
    ("Evidence supports repayment.\nAPPROVE", True),
    ("Affordability failed.\nREJECT", True),
    ("The recommendation is APPROVE.", False),
    ("Evidence.\n**REJECT**", False),
    ("REJECT\nMore text", False),
])
def test_output_format_is_separate_from_semantic_judging(output, expected):
    assert final_recommendation_format(outputs=output).value is expected


def test_replay_loads_report_without_losing_captured_process_data(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"cases": [{"scenario": "old", "process_instance_id": "pid",
        "outputs": "Affordability failed.\nREJECT", "inputs": {
            "input_variables": {"hasCollateral": False, "applicantType": "EMPLOYED"},
            "iterations": 5, "tool_calls": []}}]}))
    cases = load_cases(path, report=True)
    report = deterministic_replay(cases)
    assert cases[0]["inputs"]["process_instance_id"] == "pid"
    assert any(f["scorer"] == "step_efficiency" for f in report["failures"])


def test_invalid_or_duplicate_frozen_data_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([{"scenario": "bad", "outputs": "", "expected_verdict": "no"}]))
    with pytest.raises(ValueError, match="missing frozen output"):
        load_cases(path)


def test_bpmn_requests_a_plain_final_line():
    from xml.etree import ElementTree

    root = ElementTree.parse(Path(__file__).parents[2] / "bpmn/loan-assesment.bpmn").getroot()
    prompt = root.find(".//{http://fluxnova.finos.org/schema/1.0/ai/agent}config").attrib["systemPrompt"]
    assert "NEW final line containing EXACTLY APPROVE or REJECT" in prompt
    assert "justification explicitly connecting those values" in prompt
