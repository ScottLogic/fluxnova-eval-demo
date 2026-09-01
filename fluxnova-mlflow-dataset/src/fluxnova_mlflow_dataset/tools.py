"""``expected_tools`` rule parsing and evaluation.

A rule is a display tool-name plus an optional GitLab CI-style ``if``
condition string (e.g. ``'$applicantType == "EMPLOYED"'``) evaluated against
a run's input variables. Shared by anything that needs to know which tools a
given run *should* have called (dataset-record building, and the
``tool_correctness``/``tool_argument_correctness`` scorers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Matches:  $varName == "string"  |  $varName != true  |  $varName == 42
_IF_PATTERN = re.compile(r'^\$(?P<variable>\w+)\s*(?P<op>==|!=)\s*(?P<value>.+)$')


@dataclass
class ExpectedToolRule:
    """A single rule: ``tool`` is the display name; ``if_expr`` is an optional condition."""

    tool: str
    if_expr: str | None = None

    def matches(self, input_variables: dict[str, Any]) -> bool:
        """Return True if this rule's condition is satisfied (or absent)."""
        if self.if_expr is None:
            return True
        m = _IF_PATTERN.match(self.if_expr.strip())
        if not m:
            raise ValueError(f"Cannot parse expected_tools if expression: {self.if_expr!r}")
        variable, op, raw_value = m.group("variable"), m.group("op"), m.group("value").strip()
        resolved = _coerce(raw_value)
        actual = input_variables.get(variable)
        if op == "==":
            return actual == resolved
        return actual != resolved  # !=


def _coerce(raw: str) -> Any:
    """Cast a raw YAML expression value to its Python equivalent."""
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw


def resolve_expected_tools(rules: list[ExpectedToolRule], input_variables: dict) -> list[str]:
    """Evaluate each rule against ``input_variables`` and return matching tool names."""
    return [rule.tool for rule in rules if rule.matches(input_variables)]
