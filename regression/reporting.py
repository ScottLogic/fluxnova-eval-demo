"""Fail-closed, scenario-keyed reports shared by live regression and frozen replay."""

from __future__ import annotations

import json
import math
from numbers import Real
from pathlib import Path


def _missing(value) -> bool:
    return value is None or (isinstance(value, Real) and math.isnan(value))


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if _missing(value):
        return None
    if isinstance(value, Real) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return value


def _not_applicable(name: str, inputs: dict) -> bool:
    # Only profile-driven skips are accepted. Missing iterations/arguments in this
    # full-capture regression suite must not silently pass as scorer omissions.
    variables = inputs.get("input_variables") or {}
    return {
        "no_collateral_check_when_no_collateral": bool(variables.get("hasCollateral")),
        "no_bank_statement_for_employed_applicant": variables.get("applicantType") != "EMPLOYED",
        "no_verify_employment_for_self_employed_applicant": variables.get("applicantType") == "EMPLOYED",
        "collateral_valuation_called_correctly_when_required": not variables.get("hasCollateral"),
    }.get(name, False)


def _passes(value, minimum: float) -> bool:
    if _missing(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, Real):
        return math.isfinite(value) and value >= minimum
    return str(value).strip().lower() in {"true", "yes", "1"}


def build_report(table, expected_rows: list[dict], scorers: list[str], gate: str,
                 thresholds: dict[str, float] | None = None) -> dict:
    report = {"schema_version": 1, "gate": gate, "cases": [], "failures": []}
    by_scenario = {}
    expected_names = {row["inputs"]["scenario"] for row in expected_rows}
    for row in table.to_dict(orient="records"):
        inputs = row.get("inputs") or {}
        if isinstance(inputs, str):
            try:
                inputs = json.loads(inputs)
            except json.JSONDecodeError:
                inputs = {}
        if not isinstance(inputs, dict):
            inputs = {}
        row["inputs"] = inputs
        scenario = inputs.get("scenario")
        if scenario not in expected_names or scenario in by_scenario:
            report["failures"].append({"scenario": scenario, "scorer": "evaluation",
                                       "error": "Unknown or duplicate scenario in evaluation results"})
        else:
            by_scenario[scenario] = row
    for expected in expected_rows:
        inputs = expected["inputs"]
        scenario = inputs["scenario"]
        row = by_scenario.get(scenario, {})
        case = {"scenario": scenario, "process_instance_id": inputs.get("process_instance_id"),
                "inputs": inputs, "outputs": row.get("outputs"),
                "expectations": expected.get("expectations", {}), "scorers": {}}
        if not row or (row.get("inputs") or {}).get("process_instance_id") != case["process_instance_id"]:
            report["failures"].append({"scenario": scenario, "scorer": "evaluation",
                                       "error": "Missing result or mismatched process instance ID"})
        for name in scorers:
            value = row.get(f"{name}/value")
            error = row.get(f"{name}/error_message")
            error_code = row.get(f"{name}/error_code")
            rationale = row.get(f"{name}/rationale")
            if not _missing(error) or not _missing(error_code):
                status = "failed"
                error = error if not _missing(error) else error_code
            elif _missing(value) and _not_applicable(name, inputs):
                status = "not_applicable"
            elif _missing(value):
                status = "failed"
                error = "Missing scorer verdict (not an allowed profile skip)"
            else:
                status = "passed" if _passes(value, (thresholds or {}).get(name, 1.0)) else "failed"
            assessment = {"status": status, "value": value, "rationale": rationale, "error": error}
            case["scorers"][name] = assessment
            if status == "failed":
                report["failures"].append({"scenario": scenario,
                    "process_instance_id": case["process_instance_id"], "scorer": name, **assessment})
        report["cases"].append(case)
    return _jsonable(report)


def failure_message(report: dict) -> str:
    lines = [f"{report['gate']}: {len(report['failures'])} failure(s)"]
    for failure in report["failures"]:
        lines.append(
            f"- {failure['scenario']} (process {failure.get('process_instance_id', 'unknown')}): "
            f"{failure['scorer']}={failure.get('value')!r}; "
            f"{failure.get('error') or failure.get('rationale') or 'No rationale returned'}"
        )
    return "\n".join(lines)


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
