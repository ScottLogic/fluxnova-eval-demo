"""Tests for ``fluxnova_mlflow_dataset.tools`` and ``.goldens``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fluxnova_mlflow_dataset.goldens import load_goldens, match_golden
from fluxnova_mlflow_dataset.tools import ExpectedToolRule, resolve_expected_tools


class TestExpectedToolRule:
    def test_no_if_expr_always_matches(self):
        rule = ExpectedToolRule(tool="Check Credit Score")
        assert rule.matches({})

    def test_equality_condition(self):
        rule = ExpectedToolRule(tool="Verify Employment", if_expr='$applicantType == "EMPLOYED"')
        assert rule.matches({"applicantType": "EMPLOYED"})
        assert not rule.matches({"applicantType": "SELF_EMPLOYED"})

    def test_inequality_condition(self):
        rule = ExpectedToolRule(tool="Analyse Bank Statements", if_expr='$applicantType != "EMPLOYED"')
        assert rule.matches({"applicantType": "SELF_EMPLOYED"})
        assert not rule.matches({"applicantType": "EMPLOYED"})

    def test_boolean_condition(self):
        rule = ExpectedToolRule(tool="Value Collateral", if_expr="$hasCollateral == true")
        assert rule.matches({"hasCollateral": True})
        assert not rule.matches({"hasCollateral": False})

    def test_invalid_expression_raises(self):
        rule = ExpectedToolRule(tool="X", if_expr="not a valid expr")
        with pytest.raises(ValueError, match="Cannot parse"):
            rule.matches({})


def test_resolve_expected_tools_filters_by_condition():
    rules = [
        ExpectedToolRule(tool="Check Credit Score"),
        ExpectedToolRule(tool="Verify Employment", if_expr='$applicantType == "EMPLOYED"'),
        ExpectedToolRule(tool="Analyse Bank Statements", if_expr='$applicantType != "EMPLOYED"'),
    ]
    result = resolve_expected_tools(rules, {"applicantType": "EMPLOYED"})
    assert result == ["Check Credit Score", "Verify Employment"]


class TestGoldens:
    def test_load_goldens_returns_empty_list_when_no_path(self):
        assert load_goldens(None) == []

    def test_load_goldens_reads_json_file(self, tmp_path: Path):
        path = tmp_path / "goldens.json"
        path.write_text(json.dumps([{"expected_output": "APPROVE"}]))
        assert load_goldens(path) == [{"expected_output": "APPROVE"}]

    def test_match_golden_matches_on_metadata(self):
        goldens = [
            {
                "expected_output": "APPROVE",
                "additional_metadata": {"applicantType": "EMPLOYED", "hasCollateral": False},
            },
            {
                "expected_output": "REJECT",
                "additional_metadata": {"applicantType": "SELF_EMPLOYED", "hasCollateral": True},
            },
        ]
        result = match_golden(goldens, {"applicantType": "SELF_EMPLOYED", "hasCollateral": True})
        assert result["expected_output"] == "REJECT"

    def test_match_golden_returns_none_when_no_match(self):
        goldens = [{"expected_output": "APPROVE", "additional_metadata": {"applicantType": "EMPLOYED"}}]
        assert match_golden(goldens, {"applicantType": "SELF_EMPLOYED"}) is None
