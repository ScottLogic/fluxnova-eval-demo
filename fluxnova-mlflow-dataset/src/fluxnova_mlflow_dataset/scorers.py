"""All MLflow scorer/judge definitions for the Fluxnova loan-assessment agent.

Single source of truth for every scorer used across the project, so nothing
drifts between call sites:
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from mlflow.entities import Feedback
from mlflow.genai.scorers import Guidelines, scorer

DECISION_QUALITY_NAME = "decision_quality"
DECISION_QUALITY_RUBRIC_VERSION = "2"

# Three tool rounds (batched fraud/credit, income, affordability) plus the final
# answer. A separate collateral round is allowed when it cannot be batched.
BASE_INFERENCE_BUDGET = 4
COLLATERAL_INFERENCE_ALLOWANCE = 1

DECISION_QUALITY_GUIDELINES = [
    "The response must select one unambiguous lending recommendation: APPROVE or REJECT. "
    "Formatting, markdown and capitalization do not matter for this semantic check. "
    "Contradictory recommendations or only deferring the decision to a human/next steps fail.",
    "Read the ENTIRE response, including preceding paragraphs, bullet lists and tables. "
    "The recommendation must be supported by concrete assessment evidence, such as credit "
    "score, fraud risk score, verified income/employment, or DTI and affordability outcome. "
    "Evidence stated earlier in the response counts and need not be repeated in the final "
    "sentence. A coherent connection between at least one material assessment result and "
    "the recommendation meets the support requirement; every listed data point need not "
    "be individually connected to the conclusion. A supplied failed-affordability result "
    "supports rejection without needing an additional numeric DTI policy threshold. "
    "Do not invent requirements for policy thresholds absent from the inputs. "
    "Relevant additional context is not a reason to fail. A clear explanation is enough; "
    "do not require a particular wording, layout, citation format, or all values in one sentence. "
    "Missing evidence, fabricated facts, or reasons contradicting the supplied assessment facts "
    "fail. When inputs provide facts, use them to check claims. If failing, identify the actual "
    "missing or contradictory evidence rather than inventing additional formatting requirements.",
]


def decision_quality_judge(model: str) -> Guidelines:
    """Build the ``decision_quality`` ``Guidelines`` judge for the given model URI.

    ``model`` differs by call site: a direct ``"<provider>:/<model>"`` URI (e.g.
    ``"ollama:/llama3.2"``) for direct offline/regression evaluation, or a
    ``"gateway:/<endpoint>"`` URI for anything routed through the MLflow AI
    Gateway (automatic/online scoring, and the synchronous eval-service-worker).
    """
    return Guidelines(
        name=DECISION_QUALITY_NAME, guidelines=DECISION_QUALITY_GUIDELINES, model=model
    )


# ---------------------------------------------------------------------------
# Golden/LLM-judge scorers — grade the agent's textual output.
#
# `decision_quality` (a Guidelines judge) and `matches_golden` read
# `outputs`/`expectations` and are used by the regression suite (`regression/`);
# `evidence_citation` is an LLM judge kept available for reuse. These are
# separate from the deterministic trace-based scorers further below.
# ---------------------------------------------------------------------------

# Offline judge provider for the bespoke `_llm_judge()` helper and the native
# `decision_quality_judge()` used by the regression suite (see
# `regression/test_mlflow_regression.py`). Defaults to OpenAI; set
# LLM_JUDGE_PROVIDER=ollama to fall back to a fully local judge (e.g. when no
# OPENAI_API_KEY is available). This is independent of the BPMN agent's own
# provider toggle (`local-dev/default.yml`'s `spring.ai.model.chat`).
LLM_JUDGE_PROVIDER = os.environ.get("LLM_JUDGE_PROVIDER", "openai").lower()

# Auxiliary judges intentionally use a *different* model than the agent they are
# grading (the BPMN agent runs `gpt-4o` — see `bpmn/loan-assesment.bpmn` and
# local-dev/README.md's provider-toggle section) to avoid self-preference
# bias, while still being fast/cheap enough for many-judge-call regression
# runs. `gpt-4o-mini` is a good fit: strong instruction-following for
# guideline/JSON-scoring judge prompts, at a fraction of gpt-4o's cost.
_OPENAI_JUDGE_MODEL = "openai/gpt-4o-mini"
_OLLAMA_JUDGE_MODEL = "ollama/gemma4:e2b"

# Bespoke litellm-backed judge model, used by `_llm_judge`. Litellm-style
# "<provider>/<model>" URI.
_JUDGE_MODEL = _OPENAI_JUDGE_MODEL if LLM_JUDGE_PROVIDER == "openai" else _OLLAMA_JUDGE_MODEL

# Semantic decision-quality judging uses the separately calibrated model below.
# MLflow-native judges (e.g. Guidelines) use MLflow's own "<provider>:/<model>"
# URI scheme, which differs from the litellm-style "<provider>/<model>" used by
# the bespoke `_llm_judge()` helper above.
def decision_quality_model_for(provider: str, override: str | None = None) -> str:
    """Choose the calibrated semantic judge, independently of the auxiliary judges."""
    return override or ("openai:/gpt-4.1-mini" if provider == "openai" else "ollama:/gemma4:e2b")


_NATIVE_JUDGE_MODEL = decision_quality_model_for(
    LLM_JUDGE_PROVIDER, os.environ.get("DECISION_QUALITY_MODEL")
)

# Automatic (online) evaluation -- Scorer.register()/.start() -- requires a
# `gateway:/<endpoint-name>` model URI rather than calling Ollama directly
# (see local-dev/README.md's AI Gateway section), so the judges used
# there are separate instances built on demand by `automatic_judges` (used by
# `fluxnova_mlflow_dataset.judges`, the start/stop toggle CLI).
GATEWAY_JUDGE_MODEL = "gateway:/fluxnova-judge"

# Minimum `matches_golden` similarity score (0.0-1.0) at which the agent's output
# counts as reproducing the golden's decision + evidence, i.e. a "yes" verdict.
# Overridable via env so CI can tighten/loosen the gate without a code change.
GOLDEN_MATCH_THRESHOLD = float(os.environ.get("REGRESSION_GOLDEN_MATCH_THRESHOLD", "0.7"))

# Tool -> BPMN camunda:inputParameter names (see bpmn/loan-assesment.bpmn),
# used to validate that each tool call received the arguments the process
# actually wires up for it. Requires content capture (tool-call arguments) to
# be enabled on the trace — see the tool-argument scorers below.
_EXPECTED_TOOL_INPUTS: dict[str, list[str]] = {
    "Check Credit Score": ["customerId"],
    "Run Fraud Screening": ["applicationId", "customerId"],
    "Verify Employment": ["customerId"],
    "Analyse Bank Statements": ["customerId"],
    "Value Collateral": ["applicationId"],
    "Assess Affordability": ["customerId", "requestedAmount"],
}


def _llm_judge(criteria: str, context: dict[str, Any], model: str = _JUDGE_MODEL) -> Feedback:
    """Ask an LLM (OpenAI by default, Ollama as a local fallback — see
    ``LLM_JUDGE_PROVIDER``) to judge ``context`` against ``criteria``.

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

    Reads ``inputs["input_variables"]`` for the applicant profile. ``agent_goal``
    is optional supplementary context for the judge (available from Fluxnova's
    REST history, but not from a trace) — it's included only when the caller
    supplies it, so trace-only callers (eval-trace-listener) can run this too.
    """
    variables = (inputs or {}).get("input_variables") or {}
    applicant_type = variables.get("applicantType")
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
    context: dict[str, Any] = {"final_output": outputs}
    goal = (inputs or {}).get("agent_goal")
    if goal:
        context["goal"] = goal
    return _llm_judge(criteria, context)


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


# ---------------------------------------------------------------------------
# Deterministic (non-LLM) scorers — used by eval-service-worker,
# eval-trace-listener and the regression suite.
#
# These are self-contained: the tool-call/applicant-profile rules below are a
# hardcoded mirror of `fluxnova-runner/config/loan-assesment-eval.yml`'s
# `expected_tools` list, kept in sync manually. This keeps callers free of any
# BPMN/YAML config read at runtime, at the cost of needing a manual update here
# if that BPMN's tool set/rules ever change. See this package's README.
#
# They know nothing about tracing: each reads plain values from MLflow's
# standard `inputs`/`outputs`/`expectations` columns. The caller is responsible
# for extracting those values from whatever source suits it (a run's MLflow
# trace, process variables, etc.) and passing them via
# `mlflow.genai.evaluate(data=[{"inputs": ..., "outputs": ...}], scorers=[...])`.
# When the caller also supplies a `trace` column, MLflow still logs every
# scorer's `Feedback` back onto that *same* real trace and groups them as one
# "Evaluation Run" (feedback is linked to the row's trace regardless of which
# columns the scorer reads) — see eval_service_worker.scoring.
#
# The canonical `inputs` shape (see traces.scorer_inputs_from_trace) is:
#   {
#       "input_variables": {...},   # applicantType, hasCollateral, applicationId, ...
#       "tool_calls": [             # chronological order
#           {"name": str, "status": "OK"|"ERROR", "arguments": dict | None},
#       ],
#       "iterations": int | None,   # agent-loop / LLM inference-call count
#   }
# A tool call's "arguments" is None (not {}) when content capture is disabled.
#
# Two tiers, exposed as separate bundles at the bottom of this section:
#   - DETERMINISTIC_SCORERS   — need only tool *names*/status/input-variables/
#     iteration count, all captured by default.
#   - TOOL_ARGUMENT_SCORERS   — also inspect tool-call *arguments*, only present
#     when content capture is enabled (off by default — see local-dev/default.yml).
#     They return a "not applicable" `Feedback(None)` when arguments aren't
#     captured, so they are always safe to include.
# ---------------------------------------------------------------------------

_ALWAYS_REQUIRED_TOOLS = ("Check Credit Score", "Run Fraud Screening", "Assess Affordability")
_DECISION_KEYWORD_RE = re.compile(r"\b(APPROVE|REJECT)\b", re.IGNORECASE)


def _input_variables(inputs: dict | None) -> dict:
    """The applicant/process input variables from a scorer ``inputs`` payload."""
    return (inputs or {}).get("input_variables") or {}


def _tool_calls(inputs: dict | None) -> list[dict]:
    """The chronological tool-call records from a scorer ``inputs`` payload."""
    return (inputs or {}).get("tool_calls") or []


def _called_tool_names(inputs: dict | None, *, ok_only: bool = False) -> set[str]:
    """Names of tools called in this run (optionally only the ones that succeeded)."""
    return {
        c.get("name")
        for c in _tool_calls(inputs)
        if not ok_only or c.get("status") == "OK"
    }


def _arguments_available(calls: list[dict]) -> bool:
    """True if at least one tool call carries captured arguments."""
    return any(c.get("arguments") is not None for c in calls)


def _decision_text(outputs: Any) -> str:
    """Coerce an ``outputs`` payload to the agent's final text for keyword checks."""
    if outputs is None:
        return ""
    return outputs if isinstance(outputs, str) else json.dumps(outputs)


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
def required_tools_called(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: were exactly the tools this applicant's profile requires
    called (and none of the ones that shouldn't be), per ``_expected_tools_for``?
    """
    variables = _input_variables(inputs)
    called = _called_tool_names(inputs, ok_only=True)
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
def no_tool_errors(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: did every tool call the agent made succeed
    (no failed tool executions)?
    """
    failed = [c.get("name") for c in _tool_calls(inputs) if c.get("status") != "OK"]
    passed = not failed
    return Feedback(
        value=passed,
        rationale="No tool call errors." if passed else f"Tool call(s) failed: {failed}",
    )


@scorer
def definitive_decision_stated(outputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: does the final output literally contain an APPROVE or
    REJECT keyword? A hard syntactic check, complementing (not replacing) the
    ``decision_quality`` LLM judge's opinion on whether it's well-reasoned.
    """
    matched = bool(_DECISION_KEYWORD_RE.search(_decision_text(outputs)))
    return Feedback(
        value=matched,
        rationale=(
            "Final output states a definitive APPROVE/REJECT keyword."
            if matched
            else "Final output does not contain a definitive APPROVE or REJECT keyword."
        ),
    )


@scorer
def final_recommendation_format(outputs) -> Feedback:  # noqa: ANN001
    """Check the new agent output contract independently of semantic judging."""
    lines = _decision_text(outputs).strip().splitlines()
    passed = bool(lines) and lines[-1].strip() in {"APPROVE", "REJECT"}
    return Feedback(
        value=passed,
        rationale="Final line must be exactly APPROVE or REJECT; justification belongs above it."
        if not passed else "Final recommendation line has the required format.",
    )


@scorer
def tool_correctness(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Graded (0.0–1.0) counterpart to :func:`required_tools_called`: all tools the
    applicant's profile requires must be called, and forbidden ones penalised.

    Both derive the expected/forbidden tool set from ``_expected_tools_for``;
    this one returns a proportional score rather than a boolean.
    """
    variables = _input_variables(inputs)
    called = _called_tool_names(inputs, ok_only=True)
    required, forbidden = _expected_tools_for(variables)
    missing = required - called
    unexpected = forbidden & called
    denom = len(required | unexpected) or 1
    score = 1.0 - (len(missing) + len(unexpected)) / denom
    rationale = (
        f"missing={sorted(missing)!r}, unexpected={sorted(unexpected)!r}, "
        f"called={sorted(called)!r}, required={sorted(required)!r}"
    )
    return Feedback(value=max(0.0, score), rationale=rationale)


@scorer
def all_tool_calls_completed(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Every tool call the agent initiated must have completed without an error status."""
    failed = [c.get("name") for c in _tool_calls(inputs) if c.get("status") != "OK"]
    return Feedback(
        value=not failed,
        rationale=f"Tool calls did not complete: {failed}" if failed else "OK",
    )


@scorer
def no_collateral_check_when_no_collateral(inputs) -> Feedback | None:  # noqa: ANN001
    """Value Collateral must not be called when hasCollateral is false."""
    if _input_variables(inputs).get("hasCollateral"):
        return None  # not applicable for this run
    called = "Value Collateral" in _called_tool_names(inputs)
    return Feedback(
        value=not called,
        rationale="Value Collateral was invoked despite hasCollateral=false" if called else "OK",
    )


@scorer
def no_bank_statement_for_employed_applicant(inputs) -> Feedback | None:  # noqa: ANN001
    """Bank statement analysis must not be called for an employed (salaried) applicant."""
    if _input_variables(inputs).get("applicantType") != "EMPLOYED":
        return None
    called = "Analyse Bank Statements" in _called_tool_names(inputs)
    return Feedback(
        value=not called,
        rationale="Analyse Bank Statements was invoked for an EMPLOYED applicant" if called else "OK",
    )


@scorer
def no_verify_employment_for_self_employed_applicant(inputs) -> Feedback | None:  # noqa: ANN001
    """Employment verification must not be called for a self-employed applicant."""
    if _input_variables(inputs).get("applicantType") == "EMPLOYED":
        return None
    called = "Verify Employment" in _called_tool_names(inputs)
    return Feedback(
        value=not called,
        rationale="Verify Employment was invoked for a non-EMPLOYED applicant" if called else "OK",
    )


@scorer
def step_efficiency(inputs) -> Feedback | None:  # noqa: ANN001 - MLflow scorer signature
    """Agent must complete its assessment within a reasonable number of loop iterations.

    Counts all inference calls, including the final response (not just tool
    rounds). The baseline is four: batched fraud/credit, income verification,
    affordability after income, then the final answer. A separate collateral
    round may add one call. Variable and trace consumers use the same semantics.
    Returns ``None`` when the caller supplied no iteration count to check.
    """
    iterations = (inputs or {}).get("iterations")
    if iterations is None:
        return None
    max_iterations = BASE_INFERENCE_BUDGET + (
        COLLATERAL_INFERENCE_ALLOWANCE if _input_variables(inputs).get("hasCollateral") else 0
    )
    return Feedback(
        value=iterations <= max_iterations,
        rationale=f"Agent used {iterations} total LLM calls (including final response); budget <= {max_iterations}",
    )


@scorer
def affordability_called_after_income_confirmed(inputs) -> Feedback | None:  # noqa: ANN001
    """Affordability must be assessed only after employment/income has been confirmed.

    The BPMN's agent prompt requires Assess Affordability to run "after income
    has been confirmed" — i.e. after Verify Employment (EMPLOYED) or Analyse
    Bank Statements (otherwise). Tool calls are expected in chronological order
    (see :func:`fluxnova_mlflow_dataset.traces.scorer_inputs_from_trace`).
    """
    applicant_type = _input_variables(inputs).get("applicantType")
    income_tool = "Verify Employment" if applicant_type == "EMPLOYED" else "Analyse Bank Statements"
    names = [c.get("name") for c in _tool_calls(inputs)]
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


# --- Tool-argument scorers (require content capture) ------------------------
# These inspect each tool call's captured `arguments`, only present when content
# capture is enabled. Each returns a "not applicable" `Feedback(None)` when
# arguments aren't captured, so they're safe to include in any evaluation.


@scorer
def tool_argument_correctness(inputs) -> Feedback | None:  # noqa: ANN001 - MLflow scorer signature
    """Each required tool must be invoked with the arguments the BPMN wires up for it.

    Returns ``None`` when no tool-call arguments were captured (content capture
    disabled), since correctness cannot then be judged.
    """
    variables = _input_variables(inputs)
    calls = _tool_calls(inputs)
    if not _arguments_available(calls):
        return None
    required, _ = _expected_tools_for(variables)
    calls_by_name: dict[str, Any] = {}
    for c in calls:
        calls_by_name.setdefault(c.get("name"), c)

    problems: list[str] = []
    for tool_name in required:
        expected_params = _EXPECTED_TOOL_INPUTS.get(tool_name)
        if not expected_params:
            continue
        call = calls_by_name.get(tool_name)
        if call is None:
            problems.append(f"{tool_name}: never called")
            continue
        arguments = call.get("arguments")
        if arguments is None:
            continue  # this call's arguments weren't captured — can't check it
        for param in expected_params:
            expected_value = str(variables.get(param))
            actual_value = str(arguments.get(param))
            if expected_value != actual_value:
                problems.append(
                    f"{tool_name}.{param}: expected {expected_value!r}, got {actual_value!r}"
                )

    score = 1.0 if not problems else max(0.0, 1.0 - len(problems) / max(len(required), 1))
    rationale = "OK" if not problems else "; ".join(problems)
    return Feedback(value=score, rationale=rationale)


@scorer
def collateral_valuation_called_correctly_when_required(inputs) -> Feedback | None:  # noqa: ANN001
    """Value Collateral must be called, with the correct applicationId, when hasCollateral is true."""
    variables = _input_variables(inputs)
    if not variables.get("hasCollateral"):
        return None  # not applicable for this run
    calls = [c for c in _tool_calls(inputs) if c.get("name") == "Value Collateral"]
    if not calls:
        return Feedback(value=0.0, rationale="Value Collateral was never called despite hasCollateral=true")
    arguments = calls[0].get("arguments")
    if arguments is None:
        return None  # called, but arguments weren't captured — can't verify applicationId
    expected_application_id = str(variables.get("applicationId"))
    actual_application_id = str(arguments.get("applicationId"))
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
def requested_amount_passed_to_affordability(inputs) -> Feedback | None:  # noqa: ANN001
    """Affordability assessment must receive the correct customerId and requestedAmount."""
    calls = [c for c in _tool_calls(inputs) if c.get("name") == "Assess Affordability"]
    if not calls:
        return Feedback(value=0.0, rationale="Assess Affordability was never called")
    arguments = calls[0].get("arguments")
    if arguments is None:
        return None  # called, but arguments weren't captured — can't verify them
    variables = _input_variables(inputs)
    problems = [
        f"{param}: expected {str(variables.get(param))!r}, got {str(arguments.get(param))!r}"
        for param in ("customerId", "requestedAmount")
        if str(arguments.get(param)) != str(variables.get(param))
    ]
    return Feedback(value=not problems, rationale="; ".join(problems) if problems else "OK")


# Default bundle: checks needing no captured tool arguments — safe everywhere.
# Used by eval-service-worker, eval-trace-listener and regression.
DETERMINISTIC_SCORERS = [
    required_tools_called,
    no_tool_errors,
    definitive_decision_stated,
    final_recommendation_format,
    tool_correctness,
    all_tool_calls_completed,
    no_collateral_check_when_no_collateral,
    no_bank_statement_for_employed_applicant,
    no_verify_employment_for_self_employed_applicant,
    step_efficiency,
    affordability_called_after_income_confirmed,
]

# Opt-in bundle: scorers that inspect tool-call *arguments* — only meaningful
# when content capture is enabled (they self-skip with Feedback(None) otherwise).
TOOL_ARGUMENT_SCORERS = [
    tool_argument_correctness,
    collateral_valuation_called_correctly_when_required,
    requested_amount_passed_to_affordability,
]

# Everything deterministic — the full set, for callers that run with content
# capture on and want maximal coverage.
ALL_DETERMINISTIC_SCORERS = DETERMINISTIC_SCORERS + TOOL_ARGUMENT_SCORERS
