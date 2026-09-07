"""Shared MLflow evaluation-dataset logic for the Fluxnova services.

Used by ``harness``'s ``mlflow_eval`` suite to:
- collect newly-completed agentic subprocess runs (BPMN + MLflow trace data +
  Fluxnova core-API variables) as an on-demand pre-step (``collect_new_runs``),
  replacing the old always-running ``fluxnova_listener`` service now that the
  OTel Collector exports traces directly to MLflow; and
- read records back (single instance or the whole dataset) and score them.

Keeping this logic in one standalone, installable package guarantees what
gets written matches what gets read/evaluated.
"""

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError
from fluxnova_mlflow_dataset.collect import CollectedRun, collect_new_runs
from fluxnova_mlflow_dataset.fluxnova_client import ApiError, FluxnovaClient
from fluxnova_mlflow_dataset.goldens import load_goldens, match_golden
from fluxnova_mlflow_dataset.report import build_agent_report
from fluxnova_mlflow_dataset.scorers import (
    BATCH_SCORERS,
    DECISION_QUALITY_GUIDELINES,
    DECISION_QUALITY_NAME,
    DETERMINISTIC_SCORERS,
    GATEWAY_JUDGE_MODEL,
    affordability_called_after_income_confirmed,
    all_tool_calls_completed,
    automatic_judges,
    collateral_valuation_called_correctly_when_required,
    decision_quality,
    decision_quality_judge,
    definitive_decision_stated,
    evidence_citation,
    matches_golden,
    no_bank_statement_for_employed_applicant,
    no_collateral_check_when_no_collateral,
    no_tool_errors,
    no_verify_employment_for_self_employed_applicant,
    requested_amount_passed_to_affordability,
    required_tools_called,
    step_efficiency,
    tool_argument_correctness,
    tool_correctness,
)
from fluxnova_mlflow_dataset.store import (
    build_mlflow_record,
    dataset_name_for,
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
)

__all__ = [
    "ExpectedToolRule",
    "resolve_expected_tools",
    "load_goldens",
    "match_golden",
    "build_mlflow_record",
    "dataset_name_for",
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
    "build_agent_report",
    "collect_new_runs",
    "CollectedRun",
    "DECISION_QUALITY_NAME",
    "DECISION_QUALITY_GUIDELINES",
    "decision_quality_judge",
    "DETERMINISTIC_SCORERS",
    "required_tools_called",
    "no_tool_errors",
    "definitive_decision_stated",
    "BATCH_SCORERS",
    "GATEWAY_JUDGE_MODEL",
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
    "all_tool_calls_completed",
    "step_efficiency",
    "requested_amount_passed_to_affordability",
    "affordability_called_after_income_confirmed",
]
