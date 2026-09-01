"""
DeepEval tests for the Fluxnova loan assessment agent subprocess.

Run via the entry point (generates both the DeepEval score summary and an HTML report):
    deep-eval harness/config/loan-assesment.yml \\
              harness/.fluxnova/loanAssessmentProcess/<id>.json

The HTML report is written next to the agent-history JSON:
    harness/.fluxnova/loanAssessmentProcess/<id>-eval.html

Or invoke deepeval / pytest directly:
    deepeval test run src/deep_eval/main.py \\
        --config harness/config/loan-assesment.yml \\
        --report harness/.fluxnova/loanAssessmentProcess/<id>.json

    pytest src/deep_eval/main.py -v \\
        --config harness/config/loan-assesment.yml \\
        --report harness/.fluxnova/loanAssessmentProcess/<id>.json \\
        --html harness/.fluxnova/loanAssessmentProcess/<id>-eval.html --self-contained-html
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from deepeval import assert_test
from deepeval.metrics import GEval, ToolCorrectnessMetric
from deepeval.models import OllamaModel
from deepeval.test_case import LLMTestCase, SingleTurnParams, ToolCall, ToolCallParams

from fluxnova.config import WorkflowConfig, ExpectedToolRule

ollama = OllamaModel(model="llama3.2")

# ---------------------------------------------------------------------------
# Fixtures  (data derived from session-scoped config + report fixtures in conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def tool_calls(agent_report: dict) -> list[dict]:
    return agent_report["toolCalls"]


@pytest.fixture(scope="session")
def goal(agent_report: dict) -> str:
    return agent_report["goal"]


@pytest.fixture(scope="session")
def final_output(agent_report: dict) -> str:
    return agent_report["finalOutput"]


@pytest.fixture(scope="session")
def iterations(agent_report: dict) -> int:
    return agent_report["iterations"]


@pytest.fixture(scope="session")
def input_variables(agent_report: dict) -> dict:
    return agent_report["inputVariables"]


@pytest.fixture(scope="session")
def available_tools(workflow_config: WorkflowConfig) -> list[ToolCall]:
    """All tools available to the agent, read directly from available_tools in the config."""
    return [ToolCall(name=name) for name in workflow_config.available_tools.values()]


@pytest.fixture(scope="session")
def tools_called(tool_calls: list[dict]) -> list[ToolCall]:
    return [
        ToolCall(
            name=tc["toolName"],
            input_parameters=json.loads(tc["toolInput"]) if tc.get("toolInput") else {},
        )
        for tc in tool_calls
    ]


@pytest.fixture(scope="session")
def goldens(workflow_config: WorkflowConfig) -> list[dict]:
    """Load golden scenarios from the dataset file linked in the config.

    Each golden is a dict with at minimum ``input``, ``expected_output``, and
    ``additional_metadata`` (used to match the golden to the current run).
    """
    if not workflow_config.dataset_path:
        return []
    return json.loads(workflow_config.dataset_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_expected_tools(
    rules: list[ExpectedToolRule],
    input_variables: dict,
) -> list[ToolCall]:
    """Evaluate each rule against ``input_variables`` and return matching tools."""
    return [ToolCall(name=rule.tool) for rule in rules if rule.matches(input_variables)]


def _match_golden(goldens: list[dict], input_variables: dict) -> dict | None:
    """Return the first golden whose ``additional_metadata`` conditions all match
    the current run's ``input_variables``.

    Only the keys ``applicantType`` and ``hasCollateral`` are used for matching
    so that the same golden covers any variation of amounts or names within the
    same scenario archetype.
    """
    MATCH_KEYS = ("applicantType", "hasCollateral")
    for golden in goldens:
        meta = golden.get("additional_metadata") or {}
        if all(
            input_variables.get(k) == meta[k]
            for k in MATCH_KEYS
            if k in meta
        ):
            return golden
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_tool_correctness(goal, final_output, tools_called, available_tools, input_variables, workflow_config):
    """All core assessment tools must be called; inappropriate tools are penalised."""
    metric = ToolCorrectnessMetric(
        threshold=0.7,
        model=ollama,
        available_tools=available_tools,
    )
    test_case = LLMTestCase(
        input=goal,
        actual_output=final_output,
        tools_called=tools_called,
        expected_tools=resolve_expected_tools(workflow_config.expected_tools, input_variables),
    )
    assert_test(test_case, [metric])


def test_tool_argument_correctness(goal, final_output, tools_called, available_tools, input_variables, workflow_config):
    """Each tool must be invoked with the correct input arguments from the process variables."""
    metric = ToolCorrectnessMetric(
        threshold=0.7,
        model=ollama,
        evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
        available_tools=available_tools,
    )
    expected = [
        ToolCall(
            name="Check Credit Score",
            input_parameters={"customerId": input_variables["customerId"]},
        ),
        ToolCall(
            name="Run Fraud Screening",
            input_parameters={
                "applicationId": input_variables["applicationId"],
                "customerId": input_variables["customerId"],
            },
        ),
        ToolCall(
            name="Assess Affordability",
            input_parameters={
                "customerId": input_variables["customerId"],
                "requestedAmount": str(input_variables["requestedAmount"]),
            },
        ),
    ]
    if "Verify Employment" in {tc.name for tc in resolve_expected_tools(workflow_config.expected_tools, input_variables)}:
        expected.append(ToolCall(
            name="Verify Employment",
            input_parameters={"customerId": input_variables["customerId"]},
        ))
    test_case = LLMTestCase(
        input=goal,
        actual_output=final_output,
        tools_called=tools_called,
        expected_tools=expected,
    )
    assert_test(test_case, [metric])


def test_decision_quality(goal, final_output):
    """Final output must contain a clear, justified APPROVE or REJECT recommendation."""
    metric = GEval(
        name="Decision Quality",
        criteria=(
            "Determine whether the agent's final output reaches a definitive APPROVE or REJECT "
            "lending recommendation backed by the evidence it gathered. "
            "Penalise vague conclusions, deferred decisions ('next steps required'), or missing "
            "justification. Reward outputs that cite specific data points (credit score, fraud "
            "risk, affordability result, employment status) and state a clear recommendation."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=0.6,
        model=ollama,
    )
    assert_test(LLMTestCase(input=goal, actual_output=final_output), [metric])


def test_evidence_citation(goal, final_output):
    """Agent output must explicitly reference the key financial data points it gathered."""
    metric = GEval(
        name="Evidence Citation",
        criteria=(
            "Evaluate whether the agent's final output explicitly references the core financial data "
            "collected during the assessment: at minimum the fraud risk score, affordability outcome, "
            "and employment verification result. An output that draws a conclusion without citing "
            "specific gathered evidence should score poorly."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=0.6,
        model=ollama,
    )
    assert_test(LLMTestCase(input=goal, actual_output=final_output), [metric])


def test_output_matches_golden(goal, final_output, goldens, input_variables):
    """Final output must reach the same APPROVE/REJECT decision as the golden for this scenario."""
    if not goldens:
        pytest.skip("No dataset_path configured — skipping golden comparison test")
    golden = _match_golden(goldens, input_variables)
    if not golden:
        pytest.skip(
            f"No matching golden for applicantType={input_variables.get('applicantType')!r} "
            f"hasCollateral={input_variables.get('hasCollateral')!r}"
        )
    metric = GEval(
        name="Matches Golden",
        criteria=(
            "Compare the agent's actual output to the expected (golden) output. "
            "Award a high score if both reach the same APPROVE or REJECT decision AND "
            "the actual output cites at least the same categories of evidence (credit, "
            "fraud risk, affordability). Penalise if the decision differs or critical "
            "evidence cited in the golden is entirely absent from the actual output."
        ),
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        threshold=0.6,
        model=ollama,
    )
    test_case = LLMTestCase(
        input=goal,
        actual_output=final_output,
        expected_output=golden["expected_output"],
    )
    assert_test(test_case, [metric])


def test_no_collateral_check_when_no_collateral(tool_calls, input_variables):
    """Value Collateral must not be called when hasCollateral is false."""
    if input_variables.get("hasCollateral"):
        pytest.skip("hasCollateral is true — collateral check is expected")
    tool_names = [tc["toolName"] for tc in tool_calls]
    assert "Value Collateral" not in tool_names, (
        "Value Collateral was invoked despite hasCollateral=false"
    )


def test_no_bank_statement_for_employed_applicant(tool_calls, input_variables):
    """Bank statement analysis must not be called for an employed (salaried) applicant."""
    if input_variables.get("applicantType") != "EMPLOYED":
        pytest.skip("applicantType is not EMPLOYED — bank statement check may be appropriate")
    tool_names = [tc["toolName"] for tc in tool_calls]
    assert "Analyse Bank Statements" not in tool_names, (
        "Analyse Bank Statements was invoked for an EMPLOYED applicant"
    )


def test_all_tool_calls_completed(tool_calls):
    """Every tool call initiated by the agent must have reached COMPLETED status."""
    failed = [tc for tc in tool_calls if tc["status"] != "COMPLETED"]
    assert not failed, (
        f"Tool calls did not complete: {[tc['toolName'] for tc in failed]}"
    )


def test_step_efficiency(iterations):
    """Agent must complete its assessment within a reasonable number of loop iterations."""
    assert iterations <= 3, (
        f"Agent used {iterations} loop iterations; expected ≤ 3 for a straightforward applicant."
    )


def test_requested_amount_passed_to_affordability(tool_calls, input_variables):
    """Affordability assessment must receive the correct requestedAmount."""
    calls = [tc for tc in tool_calls if tc["toolElementId"] == "ServiceTask_AffordabilityAssessment"]
    assert calls, "Assess Affordability was never called"
    inputs = json.loads(calls[0]["toolInput"])
    assert str(inputs.get("requestedAmount")) == str(input_variables["requestedAmount"]), (
        f"requestedAmount mismatch: tool got {inputs.get('requestedAmount')!r}, "
        f"expected {input_variables['requestedAmount']!r}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run DeepEval tests against a Fluxnova agent-history report"
    )
    parser.add_argument("config", type=Path, help="Path to the workflow YAML config file")
    parser.add_argument("report", type=Path, help="Path to the agent-history JSON report file")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    here = Path(__file__).parent
    report_path = Path(args.report).resolve()
    html_report = report_path.with_name(report_path.stem + "-eval.html")

    # Use `deepeval test run` so that DeepEval's own score/reason summary is
    # generated at the end of the session. Unknown options (--config, --report,
    # --html) are forwarded by deepeval to pytest.
    deepeval_exe = Path(sys.executable).parent / "deepeval"
    cmd = [
        str(deepeval_exe), "test", "run",
        str(here / "main.py"),
        "--verbose",
        f"--config={args.config}",
        f"--report={args.report}",
        f"--html={html_report}",
        "--self-contained-html",
    ]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()


