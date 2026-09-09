"""All MLflow scorer/judge definitions for the Fluxnova loan-assessment agent.

Single source of truth for every scorer used across the project, so nothing
drifts between call sites:

- the offline batch regression/analysis suite (``harness/src/mlflow_eval/main.py``,
  ``mlflow-eval`` CLI) uses :data:`BATCH_SCORERS` — config/golden-driven scorers
  that read ``inputs``/``outputs``/``expectations`` shaped by
  ``fluxnova_mlflow_dataset.store.build_mlflow_record`` (``expected_tools``,
  ``available_tools``, tool call args, etc. sourced from the workflow YAML config
  and golden dataset);
- the synchronous ``eval-service-worker`` (a BPMN external-task worker that scores
  one just-completed subprocess run on demand — see ``EVAL-SERVICE-WORKER-PLAN.md``)
  uses :data:`DETERMINISTIC_SCORERS` plus :func:`decision_quality_judge` — trace-only
  scorers with no BPMN/YAML config read at runtime; and
- ``mlflow_eval.judges`` (the automatic/online evaluation on/off toggle CLI) uses
  :func:`automatic_judges`.

``decision_quality_judge`` in particular is shared so the *same* judge definition
(guideline text, name) is used identically by both the offline batch suite and the
synchronous worker.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from mlflow.entities import Feedback
from mlflow.genai.scorers import Guidelines, scorer

from fluxnova_mlflow_dataset.traces import (
    final_output_from_spans,
    input_variables_from_spans,
    tool_calls_from_spans,
)

DECISION_QUALITY_NAME = "decision_quality"

DECISION_QUALITY_GUIDELINES = [
    "The final output must reach a definitive APPROVE or REJECT lending recommendation. "
    "Vague conclusions or deferred decisions such as 'next steps required' do not satisfy "
    "this guideline.",
    "The final output must state its recommendation backed by evidence: it must cite "
    "specific data points gathered during the assessment, such as credit score, fraud "
    "risk, affordability result, or employment status.",
]


def decision_quality_judge(model: str) -> Guidelines:
    """Build the ``decision_quality`` ``Guidelines`` judge for the given model URI.

    ``model`` differs by call site: a direct ``"<provider>:/<model>"`` URI (e.g.
    ``"ollama:/llama3.2"``) for offline batch evaluation, or a
    ``"gateway:/<endpoint>"`` URI for anything routed through the MLflow AI
    Gateway (automatic/online scoring, and the synchronous eval-service-worker).
    """
    return Guidelines(
        name=DECISION_QUALITY_NAME, guidelines=DECISION_QUALITY_GUIDELINES, model=model
    )


# ---------------------------------------------------------------------------
# Batch/config-driven scorers — for the offline `mlflow-eval` regression suite.
#
# Unlike the deterministic scorers below (trace-only, hardcoded profile rules,
# used by eval-service-worker), these read `inputs`/`outputs`/`expectations` as
# shaped by `fluxnova_mlflow_dataset.store.build_mlflow_record` — i.e.
# `expected_tools`/`available_tools` sourced from the workflow YAML config, and
# `expectations` from the golden dataset (see `fluxnova.config.WorkflowConfig`).
# ---------------------------------------------------------------------------

# Bespoke litellm-backed judge model, used by `_llm_judge` (predates the
# MLflow-native `Guidelines` judge used by `decision_quality_judge` above).
_JUDGE_MODEL = "ollama/gemma4:e2b"

# MLflow-native judges (e.g. Guidelines) use MLflow's own "<provider>:/<model>"
# URI scheme, which differs from the litellm-style "<provider>/<model>" used by
# the bespoke `_llm_judge()` helper below. Same underlying local Ollama model.
_NATIVE_JUDGE_MODEL = "ollama:/gemma4:e2b"

# Automatic (online) evaluation -- Scorer.register()/.start() -- requires a
# `gateway:/<endpoint-name>` model URI rather than calling Ollama directly
# (see Phase 0 in EDD-AND-PRODUCTION-EVAL-ANALYSIS.md), so the judges used
# there are separate instances from the offline `BATCH_SCORERS` list below,
# built on demand by `automatic_judges` (used by `mlflow_eval.judges`, the
# start/stop toggle CLI).
GATEWAY_JUDGE_MODEL = "gateway:/fluxnova-judge"

# Minimum `matches_golden` similarity score (0.0-1.0) at which the agent's output
# counts as reproducing the golden's decision + evidence, i.e. a "yes" verdict.
# Overridable via env so CI can tighten/loosen the gate without a code change.
GOLDEN_MATCH_THRESHOLD = float(os.environ.get("REGRESSION_GOLDEN_MATCH_THRESHOLD", "0.7"))

# Tool -> BPMN camunda:inputParameter names (see bpmn/loan-assesment.bpmn),
# used to validate that each tool call received the arguments the process
# actually wires up for it.
_EXPECTED_TOOL_INPUTS: dict[str, list[str]] = {
    "Check Credit Score": ["customerId"],
    "Run Fraud Screening": ["applicationId", "customerId"],
    "Verify Employment": ["customerId"],
    "Analyse Bank Statements": ["customerId"],
    "Value Collateral": ["applicationId"],
    "Assess Affordability": ["customerId", "requestedAmount"],
}


def _tool_names(tool_calls: list[dict]) -> list[str]:
    return [tc["toolName"] for tc in tool_calls]


def _tool_input(tool_call: dict) -> dict:
    return json.loads(tool_call["toolInput"]) if tool_call.get("toolInput") else {}


def _llm_judge(criteria: str, context: dict[str, Any], model: str = _JUDGE_MODEL) -> Feedback:
    """Ask a local Ollama model to judge ``context`` against ``criteria``.

    An LLM-as-judge returning a 0.0-1.0 score plus a short rationale, parsed
    from a JSON response.
    """
    import litellm

    prompt = (
        "You are an evaluation judge. Score how well the provided data satisfies "
        "the criteria below, on a scale from 0.0 (fails completely) to 1.0 "
        "(fully satisfies).\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Data to evaluate (JSON):\n{json.dumps(context, indent=2, default=str)}\n\n"
        "Respond with ONLY a JSON object of the form "
        '{"score": <0.0-1.0>, "rationale": "<one or two sentences>"}.'
    )
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
    )
    content = response["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
        score = float(parsed["score"])
        rationale = str(parsed.get("rationale", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        score, rationale = 0.0, f"Could not parse judge response: {content!r}"
    return Feedback(value=score, rationale=rationale)


@scorer
def tool_correctness(inputs: dict, outputs: str) -> Feedback:
    """All core assessment tools must be called; inappropriate tools are penalised."""
    called = set(_tool_names(inputs["tool_calls"]))
    expected = set(inputs["expected_tools"])
    available = set(inputs["available_tools"])
    missing = expected - called
    unexpected = (called - expected) & available
    denom = len(expected | unexpected) or 1
    score = 1.0 - (len(missing) + len(unexpected)) / denom
    rationale = (
        f"missing={sorted(missing)!r}, unexpected={sorted(unexpected)!r}, "
        f"called={sorted(called)!r}, expected={sorted(expected)!r}"
    )
    return Feedback(value=max(0.0, score), rationale=rationale)


@scorer
def tool_argument_correctness(inputs: dict) -> Feedback:
    """Each expected tool must be invoked with the arguments the BPMN wires up for it."""
    expected_tools = inputs["expected_tools"]
    input_variables = inputs["input_variables"]
    calls_by_name: dict[str, dict] = {}
    for tc in inputs["tool_calls"]:
        calls_by_name.setdefault(tc["toolName"], tc)

    problems: list[str] = []
    for tool_name in expected_tools:
        expected_params = _EXPECTED_TOOL_INPUTS.get(tool_name)
        if not expected_params:
            continue
        call = calls_by_name.get(tool_name)
        if call is None:
            problems.append(f"{tool_name}: never called")
            continue
        actual_input = _tool_input(call)
        for param in expected_params:
            expected_value = str(input_variables.get(param))
            actual_value = str(actual_input.get(param))
            if expected_value != actual_value:
                problems.append(
                    f"{tool_name}.{param}: expected {expected_value!r}, got {actual_value!r}"
                )

    score = 1.0 if not problems else max(0.0, 1.0 - len(problems) / max(len(expected_tools), 1))
    rationale = "OK" if not problems else "; ".join(problems)
    return Feedback(value=score, rationale=rationale)


decision_quality = decision_quality_judge(_NATIVE_JUDGE_MODEL)


def automatic_judges(model: str = GATEWAY_JUDGE_MODEL) -> list[Guidelines]:
    """Build the gateway-backed judges usable with automatic (online) evaluation.

    Currently just the one Phase-2 judge rewritten so far (`decision_quality`);
    extend this list as more judges get rewritten as MLflow-native.
    """
    return [
        decision_quality_judge(model),
    ]


@scorer
def evidence_citation(inputs: dict, outputs: str) -> Feedback:
    """Output must explicitly reference the key financial data points gathered.

    The required evidence categories depend on applicantType: EMPLOYED applicants
    are verified via employment verification, others via bank statement analysis.
    """
    applicant_type = inputs["input_variables"].get("applicantType")
    income_evidence = (
        "employment verification result" if applicant_type == "EMPLOYED"
        else "bank statement analysis result"
    )
    criteria = (
        "Evaluate whether the agent's final output explicitly references the core financial "
        "data collected during the assessment: at minimum the fraud risk score, the "
        f"affordability outcome, and the {income_evidence}. An output that draws a conclusion "
        "without citing specific gathered evidence should score poorly."
    )
    return _llm_judge(criteria, {"goal": inputs["agent_goal"], "final_output": outputs})


@scorer
def matches_golden(outputs: str, expectations: dict) -> Feedback | None:
    """Final output must reach the same APPROVE/REJECT decision as the golden for this scenario.

    The underlying LLM judge yields a graduated 0.0-1.0 similarity score, but this
    scorer returns a ``"yes"``/``"no"`` pass/fail verdict (thresholded at
    :data:`GOLDEN_MATCH_THRESHOLD`) as its feedback *value* so the MLflow GenAI
    evaluation UI renders it as a pass/fail badge (numeric feedback values are
    only shown as bare scores, never as pass/fail). The raw score is preserved in
    the feedback ``metadata`` under ``"score"`` for anyone who needs the gradation.
    """
    expected_output = expectations.get("expected_output")
    if not expected_output:
        return None
    criteria = (
        "Compare the agent's actual output to the expected (golden) output. Award a high score "
        "if both reach the same APPROVE or REJECT decision AND the actual output cites at "
        "least the same categories of evidence (credit, fraud risk, affordability). Penalise "
        "if the decision differs or critical evidence cited in the golden is entirely absent "
        "from the actual output."
    )
    judged = _llm_judge(criteria, {"actual_output": outputs, "golden_output": expected_output})
    score = float(judged.value)
    passed = score >= GOLDEN_MATCH_THRESHOLD
    return Feedback(
        value="yes" if passed else "no",
        rationale=judged.rationale,
        metadata={"score": f"{score:.4f}", "threshold": f"{GOLDEN_MATCH_THRESHOLD:.4f}"},
    )


@scorer
def no_collateral_check_when_no_collateral(inputs: dict) -> Feedback | None:
    """Value Collateral must not be called when hasCollateral is false."""
    if inputs["input_variables"].get("hasCollateral"):
        return None  # not applicable for this run
    called = "Value Collateral" in _tool_names(inputs["tool_calls"])
    return Feedback(
        value=not called,
        rationale="Value Collateral was invoked despite hasCollateral=false" if called else "OK",
    )


@scorer
def collateral_valuation_called_correctly_when_required(inputs: dict) -> Feedback | None:
    """Value Collateral must be called, with the correct applicationId, when hasCollateral is true."""
    input_variables = inputs["input_variables"]
    if not input_variables.get("hasCollateral"):
        return None  # not applicable for this run
    calls = [tc for tc in inputs["tool_calls"] if tc["toolName"] == "Value Collateral"]
    if not calls:
        return Feedback(value=0.0, rationale="Value Collateral was never called despite hasCollateral=true")
    actual_input = _tool_input(calls[0])
    expected_application_id = str(input_variables.get("applicationId"))
    actual_application_id = str(actual_input.get("applicationId"))
    if actual_application_id != expected_application_id:
        return Feedback(
            value=0.0,
            rationale=(
                f"Value Collateral applicationId mismatch: expected {expected_application_id!r}, "
                f"got {actual_application_id!r}"
            ),
        )
    return Feedback(value=1.0, rationale="OK")


@scorer
def no_bank_statement_for_employed_applicant(inputs: dict) -> Feedback | None:
    """Bank statement analysis must not be called for an employed (salaried) applicant."""
    if inputs["input_variables"].get("applicantType") != "EMPLOYED":
        return None
    called = "Analyse Bank Statements" in _tool_names(inputs["tool_calls"])
    return Feedback(
        value=not called,
        rationale="Analyse Bank Statements was invoked for an EMPLOYED applicant" if called else "OK",
    )


@scorer
def no_verify_employment_for_self_employed_applicant(inputs: dict) -> Feedback | None:
    """Employment verification must not be called for a self-employed applicant."""
    if inputs["input_variables"].get("applicantType") == "EMPLOYED":
        return None
    called = "Verify Employment" in _tool_names(inputs["tool_calls"])
    return Feedback(
        value=not called,
        rationale="Verify Employment was invoked for a non-EMPLOYED applicant" if called else "OK",
    )


@scorer
def all_tool_calls_completed(inputs: dict) -> Feedback:
    """Every tool call initiated by the agent must have reached COMPLETED status."""
    failed = [tc for tc in inputs["tool_calls"] if tc["status"] != "COMPLETED"]
    return Feedback(
        value=not failed,
        rationale=f"Tool calls did not complete: {[tc['toolName'] for tc in failed]}" if failed else "OK",
    )


@scorer
def step_efficiency(inputs: dict) -> Feedback:
    """Agent must complete its assessment within a reasonable number of loop iterations.

    The base budget is 3 LLM inference calls (fraud, credit, and either
    employment-verification or bank-statement-analysis, then affordability);
    an extra iteration is allowed when collateral valuation is also required.
    """
    max_iterations = 3 + (1 if inputs["input_variables"].get("hasCollateral") else 0)
    iterations = inputs["iterations"]
    return Feedback(
        value=iterations <= max_iterations,
        rationale=(
            "OK" if iterations <= max_iterations
            else f"Agent used {iterations} iterations; expected <= {max_iterations}"
        ),
    )


@scorer
def requested_amount_passed_to_affordability(inputs: dict) -> Feedback:
    """Affordability assessment must receive the correct customerId and requestedAmount."""
    calls = [tc for tc in inputs["tool_calls"] if tc["toolElementId"] == "ServiceTask_AffordabilityAssessment"]
    if not calls:
        return Feedback(value=0.0, rationale="Assess Affordability was never called")
    actual_input = _tool_input(calls[0])
    input_variables = inputs["input_variables"]
    problems = [
        f"{param}: expected {str(input_variables[param])!r}, got {str(actual_input.get(param))!r}"
        for param in ("customerId", "requestedAmount")
        if str(actual_input.get(param)) != str(input_variables[param])
    ]
    return Feedback(value=not problems, rationale="; ".join(problems) if problems else "OK")


@scorer
def affordability_called_after_income_confirmed(inputs: dict) -> Feedback | None:
    """Affordability must be assessed only after employment/income has been confirmed.

    The BPMN's agent prompt requires Assess Affordability to run "after income
    has been confirmed" — i.e. after Verify Employment (EMPLOYED) or Analyse
    Bank Statements (otherwise). Tool calls are assumed to be ordered
    chronologically, as produced by fluxnova.report.build_agent_report.
    """
    applicant_type = inputs["input_variables"].get("applicantType")
    income_tool = "Verify Employment" if applicant_type == "EMPLOYED" else "Analyse Bank Statements"
    names = _tool_names(inputs["tool_calls"])
    if income_tool not in names or "Assess Affordability" not in names:
        return None  # covered by tool_correctness if either is missing entirely
    income_index = names.index(income_tool)
    affordability_index = names.index("Assess Affordability")
    ok = affordability_index > income_index
    return Feedback(
        value=ok,
        rationale=(
            "OK" if ok
            else f"Assess Affordability (index {affordability_index}) ran before "
                 f"{income_tool} (index {income_index})"
        ),
    )


BATCH_SCORERS = [
    tool_correctness,
    tool_argument_correctness,
    decision_quality,
    evidence_citation,
    matches_golden,
    no_collateral_check_when_no_collateral,
    collateral_valuation_called_correctly_when_required,
    no_bank_statement_for_employed_applicant,
    no_verify_employment_for_self_employed_applicant,
    all_tool_calls_completed,
    step_efficiency,
    requested_amount_passed_to_affordability,
    affordability_called_after_income_confirmed,
]

# ---------------------------------------------------------------------------
# Deterministic (non-LLM) scorers — trace-only, for eval-service-worker.
#
# Unlike `BATCH_SCORERS` above (which read `expected_tools`/`available_tools`
# straight out of the workflow YAML config), these are self-contained: the
# tool-call/applicant-profile rules below are a hardcoded mirror of
# `config/loan-assesment-eval.yml`'s `expected_tools` list, kept in sync
# manually. This keeps eval-service-worker trace-only (no BPMN/YAML config
# read at runtime) at the cost of needing a manual update here if that BPMN's
# tool set/rules ever change. See EVAL-SERVICE-WORKER-PLAN.md.
#
# Each takes MLflow's `trace` parameter directly (rather than `inputs`/
# `outputs`) so `mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])`
# logs every scorer's ``Feedback`` back onto that *same* real trace, and groups
# them together as one MLflow "Evaluation Run" — see eval_service_worker.scoring.
# ---------------------------------------------------------------------------

_ALWAYS_REQUIRED_TOOLS = ("Check Credit Score", "Run Fraud Screening", "Assess Affordability")
_DECISION_KEYWORD_RE = re.compile(r"\b(APPROVE|REJECT)\b", re.IGNORECASE)


def _expected_tools_for(variables: dict) -> tuple[set[str], set[str]]:
    """Return ``(required, forbidden)`` tool display-names for one applicant profile."""
    required = set(_ALWAYS_REQUIRED_TOOLS)
    forbidden: set[str] = set()
    if variables.get("applicantType") == "EMPLOYED":
        required.add("Verify Employment")
        forbidden.add("Analyse Bank Statements")
    else:
        required.add("Analyse Bank Statements")
        forbidden.add("Verify Employment")
    if variables.get("hasCollateral"):
        required.add("Value Collateral")
    else:
        forbidden.add("Value Collateral")
    return required, forbidden


@scorer
def required_tools_called(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: were exactly the tools this applicant's profile requires
    called (and none of the ones that shouldn't be), per ``_expected_tools_for``?
    """
    spans = trace.data.spans
    variables = input_variables_from_spans(spans)
    called = {c.tool_name for c in tool_calls_from_spans(spans) if c.status == "OK"}
    required, forbidden = _expected_tools_for(variables)
    missing = required - called
    unexpected = forbidden & called
    passed = not missing and not unexpected
    problems = []
    if missing:
        problems.append(f"missing required tool call(s): {sorted(missing)}")
    if unexpected:
        problems.append(f"unexpected tool call(s) for this applicant profile: {sorted(unexpected)}")
    return Feedback(
        value=passed,
        rationale="; ".join(problems)
                  or "All tools required for this applicant profile were called, and no unexpected ones were.",
    )


@scorer
def no_tool_errors(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: did every tool call the agent made succeed
    (no ``execute_tool`` span errors)?
    """
    failed = [c.tool_name for c in tool_calls_from_spans(trace.data.spans) if c.status != "OK"]
    passed = not failed
    return Feedback(
        value=passed,
        rationale="No tool call errors." if passed else f"Tool call(s) failed: {failed}",
    )


@scorer
def definitive_decision_stated(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: does the final output literally contain an APPROVE or
    REJECT keyword? A hard syntactic check, complementing (not replacing) the
    ``decision_quality`` LLM judge's opinion on whether it's well-reasoned.
    """
    output = final_output_from_spans(trace.data.spans) or ""
    matched = bool(_DECISION_KEYWORD_RE.search(output))
    return Feedback(
        value=matched,
        rationale=(
            "Final output states a definitive APPROVE/REJECT keyword."
            if matched
            else "Final output does not contain a definitive APPROVE or REJECT keyword."
        ),
    )


DETERMINISTIC_SCORERS = [required_tools_called, no_tool_errors, definitive_decision_stated]
