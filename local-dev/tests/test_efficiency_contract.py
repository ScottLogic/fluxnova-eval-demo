from pathlib import Path
from xml.etree import ElementTree

from fluxnova_mlflow_dataset.scorers import step_efficiency
from fluxnova_runner.agent_tool_calls import iterations_from_variables


def test_final_answer_is_counted_and_one_extra_unnecessary_round_fails():
    assert iterations_from_variables({"_agentLoopIndex": 4}) == 4
    inputs = {"input_variables": {"hasCollateral": False}, "iterations": 4}
    assert step_efficiency(inputs=inputs).value is True
    assert step_efficiency(inputs={**inputs, "iterations": 5}).value is False


def test_deployed_bpmn_requests_batching_and_preserves_income_dependency():
    root = ElementTree.parse(Path(__file__).parents[2] / "bpmn/loan-assesment.bpmn").getroot()
    config = root.find(".//{http://fluxnova.finos.org/schema/1.0/ai/agent}config")
    prompt = config.attrib["systemPrompt"]
    assert "Run Fraud Screening and Check Credit Score together" in prompt
    assert "Assess Affordability only after" in prompt
    assert "including the final answer" in prompt
