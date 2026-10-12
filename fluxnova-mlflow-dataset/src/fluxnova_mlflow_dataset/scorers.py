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

DECISION_QUALITY_GUIDELINES = [
    "The final output must reach a definitive APPROVE or REJECT lending recommendation. "
    "Ordinary phrasing of a definitive decision — e.g. 'I recommend APPROVE', "
    "'Recommendation: REJECT', or 'My decision is to APPROVE' — fully satisfies this "
    "guideline; the word 'recommend' here is just how the decision is phrased, not a sign "
    "of hedging. Only mark this guideline as failed for conclusions that are actually "
    "vague or deferred, such as 'further review required', 'additional information "
    "needed', or 'next steps required' — i.e. cases with no clear APPROVE/REJECT outcome "
    "at all.",
    "The final output must state its recommendation backed by evidence: it must cite "
    "specific data points gathered during the assessment, such as credit score, fraud "
    "risk, affordability result, or employment status.",
]


def decision_quality_judge(model: str) -> Guidelines:
    """Build the ``decision_quality`` ``Guidelines`` judge for the given model URI.

    ``model`` differs by call site: a direct ``"<provider>:/<model>"`` URI (e.g.
    ``"ollama:/llama3.2"``) for direct offline/regression evaluation, or a
    ``"gateway:/<endpoint>"`` URI for anything routed through the MLflow AI
    Gateway (automatic/online scoring, and the synchronous eval-service-worker).
    """
    return Guidelines(
        name=DECISION_QUALITY_NAME, guidelines=DECISION_QUALITY_GUIDELINES, model=model,
        description="Evaluate whether the agent's response follows specific constraints or instructions provided in the guidelines. For example: The final output must reach a definitive APPROVE or REJECT lending recommendation."
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

# The judge intentionally uses a *different* model than the agent it's
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

# MLflow-native judges (e.g. Guidelines) use MLflow's own "<provider>:/<model>"
# URI scheme, which differs from the litellm-style "<provider>/<model>" used by
# the bespoke `_llm_judge()` helper above.
_NATIVE_JUDGE_MODEL = "openai:/gpt-4o-mini" if LLM_JUDGE_PROVIDER == "openai" else "ollama:/gemma4:e2b"

# Automatic (online) evaluation -- Scorer.register()/.start() -- requires a
# `gateway:/<endpoint-name>` model URI rather than calling Ollama directly
# (see Phase 0 in EDD-AND-PRODUCTION-EVAL-ANALYSIS.md), so the judges used
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
        # Without an explicit timeout, a single hung request (observed in
        # practice: a trace-listener run stuck "RUNNING" in MLflow for 26+
        # minutes with no further log output, no CPU activity, and no error —
        # network/auth to the provider both verified fine in isolation) blocks
        # this scorer, and therefore the whole evaluate() call, forever. 60s is
        # generous for a short JSON-scoring prompt; num_retries bounds the
        # total worst case to a few minutes instead of indefinite.
        timeout=60,
        num_retries=2,
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
    """
    Evaluate whether the agent's final output explicitly references the core financial data collected during the assessment.
    An output that draws a conclusion without citing specific gathered evidence should score poorly.
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
    """
    Compare the agent's actual output to the expected (golden) output. Award a high score if both reach the same
    APPROVE or REJECT decision AND the actual output cites at least the same categories of evidence.
    Penalise if the decision differs or critical evidence cited in the golden is entirely absent from the actual output.
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
# if that BPMN's tool set/rules ever change. See EVAL-SERVICE-WORKER-PLAN.md.
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
# Verb forms only ("I recommend REJECTING..." is a decision), not the nouns
# "approval"/"rejection", which also appear in neutral text like "loan approval process".
_DECISION_KEYWORD_RE = re.compile(r"\b(APPROV(?:E|ED|ING)|REJECT(?:ED|ING)?)\b", re.IGNORECASE)
_EVIDENCE_TERM_PATTERNS: dict[str, re.Pattern[str]] = {
    "credit": re.compile(r"credit", re.IGNORECASE),
    "fraud": re.compile(r"fraud", re.IGNORECASE),
    "affordability": re.compile(r"afford", re.IGNORECASE),
}


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
def no_tool_errors(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """
    Did every tool call the agent made succeed
    """
    failed = [c.get("name") for c in _tool_calls(inputs) if c.get("status") != "OK"]
    passed = not failed
    return Feedback(
        value=passed,
        rationale="No tool call errors." if passed else f"Tool call(s) failed: {failed}",
    )


@scorer
def definitive_decision_stated(outputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """
    Does the final output literally contain an APPROVE or REJECT keyword (or its
    -ED/-ING form, e.g. "I recommend REJECTING")?
    A hard syntactic check, complementing (not replacing)
    the decision_quality LLM judge's opinion on whether it's well-reasoned.
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
def cites_key_evidence_terms(outputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """
    Hard syntactic check that the final output mentions the core evidence
    categories (credit, fraud, affordability) by name. A free, always-on proxy
    for the evidence_citation LLM judge — complements (not replaces) that
    judge's opinion on whether the evidence is well-integrated, the same
    relationship definitive_decision_stated has with decision_quality.
    """
    text = _decision_text(outputs)
    missing = [term for term, pattern in _EVIDENCE_TERM_PATTERNS.items() if not pattern.search(text)]
    return Feedback(
        value=not missing,
        rationale=(
            f"Final output does not mention: {missing}" if missing
            else "Final output cites credit, fraud, and affordability evidence."
        ),
    )


@scorer
def tool_correctness(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Graded (0.0-1.0) check that the agent called exactly the tool set this
    applicant's profile requires based on the inputs. This gives a holistic score of the overall tool correctness
    which compliments the more specific individual tool scorers.
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


def _assert_tool_not_called(inputs: dict | None, tool_name: str, reason: str) -> Feedback:
    """Shared body for the profile-specific "forbidden tool" scorers below.

    Each of those scorers already establishes applicability itself (returning
    ``None`` when the rule doesn't apply to this run's profile) before calling
    this — it just reports whether ``tool_name`` was actually called.
    """
    called = tool_name in _called_tool_names(inputs)
    return Feedback(
        value=not called,
        rationale=f"{tool_name} was invoked despite {reason}" if called else "OK",
    )


@scorer
def no_collateral_check_when_no_collateral(inputs) -> Feedback | None:  # noqa: ANN001
    """Value Collateral must not be called when hasCollateral is false."""
    if _input_variables(inputs).get("hasCollateral"):
        return None  # not applicable for this run
    return _assert_tool_not_called(inputs, "Value Collateral", "hasCollateral=false")


@scorer
def no_bank_statement_for_employed_applicant(inputs) -> Feedback | None:  # noqa: ANN001
    """Bank statement analysis must not be called for an employed (salaried) applicant."""
    if _input_variables(inputs).get("applicantType") != "EMPLOYED":
        return None
    return _assert_tool_not_called(inputs, "Analyse Bank Statements", "applicantType=EMPLOYED")


@scorer
def no_verify_employment_for_self_employed_applicant(inputs) -> Feedback | None:  # noqa: ANN001
    """Employment verification must not be called for a self-employed applicant."""
    if _input_variables(inputs).get("applicantType") == "EMPLOYED":
        return None
    return _assert_tool_not_called(inputs, "Verify Employment", "applicantType != EMPLOYED")


@scorer
def no_duplicate_tool_calls(inputs) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """
    No tool should be called more than once (successfully) in a single run — a
    repeat call usually means the agent looped or re-derived a result it
    already had, a different failure mode from tool_correctness (which only
    checks presence/absence, not call count).
    """
    called_names = [c.get("name") for c in _tool_calls(inputs) if c.get("status") == "OK"]
    duplicates = sorted({name for name in called_names if called_names.count(name) > 1})
    return Feedback(
        value=not duplicates,
        rationale=f"Tool(s) called more than once: {duplicates}" if duplicates else "OK",
    )


@scorer
def risk_checks_precede_affordability(inputs) -> Feedback | None:  # noqa: ANN001
    """
    Check Credit Score and Run Fraud Screening must both complete before Assess
    Affordability runs — affordability should be assessed against an already-known
    risk profile. Extends affordability_called_after_income_confirmed's ordering
    check (income verification before affordability) to the other two
    prerequisite checks.
    """
    names = [c.get("name") for c in _tool_calls(inputs)]
    if "Assess Affordability" not in names:
        return None  # covered by tool_correctness if missing entirely
    affordability_index = names.index("Assess Affordability")
    out_of_order = [
        tool_name
        for tool_name in ("Check Credit Score", "Run Fraud Screening")
        if tool_name in names and names.index(tool_name) > affordability_index
    ]
    return Feedback(
        value=not out_of_order,
        rationale=(
            "OK" if not out_of_order
            else f"Assess Affordability (index {affordability_index}) ran before: {out_of_order}"
        ),
    )


@scorer
def step_efficiency(inputs) -> Feedback | None:  # noqa: ANN001 - MLflow scorer signature
    """Agent must complete its assessment within a reasonable number of loop iterations.

    The base budget is 3 LLM inference calls (fraud, credit, and either
    employment-verification or bank-statement-analysis, then affordability);
    an extra iteration is allowed when collateral valuation is also required.
    """
    iterations = (inputs or {}).get("iterations")
    if iterations is None:
        return None
    max_iterations = 3 + (1 if _input_variables(inputs).get("hasCollateral") else 0)
    return Feedback(
        value=iterations <= max_iterations,
        rationale=(
            "OK" if iterations <= max_iterations
            else f"Agent used {iterations} iterations; expected <= {max_iterations}"
        ),
    )


@scorer
def affordability_called_after_income_confirmed(inputs) -> Feedback | None:  # noqa: ANN001
    """
    Affordability must be assessed only after employment/income has been confirmed.
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
    """
    Each required tool must be invoked with the arguments the BPMN wires up for it.
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
    """
    Value Collateral must be called, with the correct applicationId, when hasCollateral is true.
    """
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
    """
    Affordability assessment must receive the correct customerId and requestedAmount.
    """
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
    tool_correctness,
    no_tool_errors,
    definitive_decision_stated,
    cites_key_evidence_terms,
    no_collateral_check_when_no_collateral,
    no_bank_statement_for_employed_applicant,
    no_verify_employment_for_self_employed_applicant,
    step_efficiency,
    affordability_called_after_income_confirmed,
    risk_checks_precede_affordability,
    no_duplicate_tool_calls,
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
