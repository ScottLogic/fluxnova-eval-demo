"""Shared MLflow evaluation-dataset logic for the Fluxnova eval services.

Provides the building blocks the eval services share:
- read records back (single instance or the whole dataset) and score them;
- the shared scorer/judge definitions (``scorers.py``) — the deterministic
  value-based scorers used by ``eval-service-worker``/``eval-trace-listener``
  (and the regression suite), the golden/config-driven scorers used by
  ``regression/`` (plus more kept available for reuse), and the
  ``decision_quality`` judge; and
- the ``mlflow-judges`` online-evaluation toggle CLI (``judges.py``).

Keeping this logic in one standalone, installable package guarantees what
gets written matches what gets read/evaluated.
"""

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError
from fluxnova_mlflow_dataset.fluxnova_client import ApiError, FluxnovaClient
from fluxnova_mlflow_dataset.goldens import load_goldens, match_golden
from fluxnova_mlflow_dataset.scorers import (
    ALL_DETERMINISTIC_SCORERS,
    DECISION_QUALITY_GUIDELINES,
    DECISION_QUALITY_NAME,
    DETERMINISTIC_SCORERS,
    GATEWAY_JUDGE_MODEL,
    GOLDEN_MATCH_THRESHOLD,
    TOOL_ARGUMENT_SCORERS,
    affordability_called_after_income_confirmed,
    automatic_judges,
    cites_key_evidence_terms,
    collateral_valuation_called_correctly_when_required,
    decision_quality,
    decision_quality_judge,
    definitive_decision_stated,
    evidence_citation,
    matches_golden,
    no_bank_statement_for_employed_applicant,
    no_collateral_check_when_no_collateral,
    no_duplicate_tool_calls,
    no_tool_errors,
    no_verify_employment_for_self_employed_applicant,
    requested_amount_passed_to_affordability,
    risk_checks_precede_affordability,
    step_efficiency,
    tool_argument_correctness,
    tool_correctness,
)
from fluxnova_mlflow_dataset.store import (
    build_mlflow_record,
    dataset_name_for,
    default_server_tracking_uri,
    default_tracking_uri,
    experiment_name_for,
    get_or_create_dataset,
    record_exists,
    stringify_output,
    tracking_uri_for,
    write_to_mlflow_dataset,
)
from fluxnova_mlflow_dataset.tools import ExpectedToolRule, resolve_expected_tools
from fluxnova_mlflow_dataset.traces import (
    ChatMessages,
    InvokeAgentMetrics,
    MlflowTraceReader,
    ToolCallSpan,
    TraceStoreError,
    final_output_from_spans,
    scorer_inputs_from_trace,
)

__all__ = [
    "ExpectedToolRule",
    "resolve_expected_tools",
    "load_goldens",
    "match_golden",
    "build_mlflow_record",
    "dataset_name_for",
    "default_server_tracking_uri",
    "default_tracking_uri",
    "experiment_name_for",
    "get_or_create_dataset",
    "record_exists",
    "stringify_output",
    "tracking_uri_for",
    "write_to_mlflow_dataset",
    "BpmnLookup",
    "BpmnLookupError",
    "FluxnovaClient",
    "ApiError",
    "MlflowTraceReader",
    "TraceStoreError",
    "InvokeAgentMetrics",
    "ToolCallSpan",
    "ChatMessages",
    "final_output_from_spans",
    "scorer_inputs_from_trace",
    "DECISION_QUALITY_NAME",
    "DECISION_QUALITY_GUIDELINES",
    "decision_quality_judge",
    "DETERMINISTIC_SCORERS",
    "TOOL_ARGUMENT_SCORERS",
    "ALL_DETERMINISTIC_SCORERS",
    "no_tool_errors",
    "definitive_decision_stated",
    "cites_key_evidence_terms",
    "GATEWAY_JUDGE_MODEL",
    "GOLDEN_MATCH_THRESHOLD",
    "automatic_judges",
    "decision_quality",
    "tool_correctness",
    "tool_argument_correctness",
    "evidence_citation",
    "matches_golden",
    "no_collateral_check_when_no_collateral",
    "collateral_valuation_called_correctly_when_required",
    "no_bank_statement_for_employed_applicant",
    "no_verify_employment_for_self_employed_applicant",
    "no_duplicate_tool_calls",
    "risk_checks_precede_affordability",
    "step_efficiency",
    "requested_amount_passed_to_affordability",
    "affordability_called_after_income_confirmed",
]
