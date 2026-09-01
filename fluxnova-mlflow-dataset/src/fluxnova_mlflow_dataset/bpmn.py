"""BPMN-lookup helper for statically-defined agent config.
Grabs the values useful for metrics and tracing that are statically available already in the bpmn
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

_NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "camunda": "http://camunda.org/schema/1.0/bpmn",
    "agent": "http://fluxnova.finos.org/schema/1.0/ai/agent",
}


class BpmnLookupError(Exception):
    """Raised when a requested BPMN element/attribute cannot be found."""


@dataclass
class ToolInputOutputParams:
    """Parameter names declared on one ``serviceTask``'s ``camunda:inputOutput``."""

    input_params: list[str]
    output_params: list[str]


class BpmnLookup:
    """Parses a BPMN file once and exposes its static agent config.

    Args:
        bpmn_path: Path to the ``.bpmn`` file (e.g. ``WorkflowConfig.bpmn_path``).
        subprocess_id: BPMN element ID of the ad-hoc subprocess carrying the
                       ``agent:config``/``agent:context`` extension elements
                       (e.g. ``WorkflowConfig.subprocess_id``).
    """

    def __init__(self, bpmn_path: Path | str, subprocess_id: str) -> None:
        self._bpmn_path = Path(bpmn_path)
        self._subprocess_id = subprocess_id
        self._root = ElementTree.parse(self._bpmn_path).getroot()

    def system_prompt(self) -> str:
        """Return the agent's ``systemPrompt``, as authored on ``agent:config``."""
        config = self._agent_config_element()
        prompt = config.get("systemPrompt")
        if prompt is None:
            raise BpmnLookupError(
                f"'{self._subprocess_id}' has no agent:config@systemPrompt in {self._bpmn_path}"
            )
        return prompt

    def context_variable_names(self) -> list[str]:
        """Return the agent's context variable names, from ``agent:context``."""
        subprocess = self._subprocess_element()
        context = subprocess.find("./bpmn:extensionElements/agent:context", _NS)
        if context is None:
            raise BpmnLookupError(
                f"'{self._subprocess_id}' has no agent:context in {self._bpmn_path}"
            )
        names = (variable.get("name") for variable in context.findall("agent:variable", _NS))
        return [name for name in names if name is not None]

    def tool_input_output_params(self, activity_id: str) -> ToolInputOutputParams:
        """Return the input/output parameter names for one ``serviceTask``.

        Args:
            activity_id: The BPMN element ID of the ``serviceTask``
                         (e.g. ``ServiceTask_FraudScreening``).
        """
        task = self._root.find(f".//bpmn:serviceTask[@id='{activity_id}']", _NS)
        if task is None:
            raise BpmnLookupError(f"No serviceTask with id '{activity_id}' in {self._bpmn_path}")
        input_output = task.find("./bpmn:extensionElements/camunda:inputOutput", _NS)
        if input_output is None:
            return ToolInputOutputParams(input_params=[], output_params=[])
        input_names = (param.get("name") for param in input_output.findall("camunda:inputParameter", _NS))
        input_params = [name for name in input_names if name is not None]
        output_names = (param.get("name") for param in input_output.findall("camunda:outputParameter", _NS))
        output_params = [name for name in output_names if name is not None]
        return ToolInputOutputParams(input_params=input_params, output_params=output_params)

    def tool_names(self) -> dict[str, str | None]:
        """Return every ``serviceTask``'s ``{element id: display name}`` mapping."""
        result: dict[str, str | None] = {}
        for task in self._root.findall(".//bpmn:serviceTask", _NS):
            task_id = task.get("id")
            if task_id is not None:
                result[task_id] = task.get("name")
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _subprocess_element(self) -> ElementTree.Element:
        subprocess = self._root.find(
            f".//bpmn:adHocSubProcess[@id='{self._subprocess_id}']", _NS
        )
        if subprocess is None:
            raise BpmnLookupError(
                f"No adHocSubProcess with id '{self._subprocess_id}' in {self._bpmn_path}"
            )
        return subprocess

    def _agent_config_element(self) -> ElementTree.Element:
        subprocess = self._subprocess_element()
        config = subprocess.find("./bpmn:extensionElements/agent:config", _NS)
        if config is None:
            raise BpmnLookupError(
                f"'{self._subprocess_id}' has no agent:config in {self._bpmn_path}"
            )
        return config
