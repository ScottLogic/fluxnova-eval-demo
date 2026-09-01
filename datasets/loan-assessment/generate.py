"""
Generate (or regenerate) the loan-assessment golden dataset using DeepEval's Synthesizer.

This script uses ``generate_goldens_from_scratch()`` with a domain-specific StylingConfig
to produce realistic loan assessment scenarios. The output is saved to goldens.json in the
same directory as this script.

Usage (from the harness directory with the venv active):
    python ../datasets/loan-assessment/generate.py

Requirements:
    pip install deepeval ollama
    ollama pull llama3.2   (or set OPENAI_API_KEY to use GPT instead)
"""

from __future__ import annotations

from pathlib import Path

from deepeval.models import OllamaModel
from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import StylingConfig

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent
NUM_GOLDENS = 10

# Use Ollama locally. Replace with OllamaModel("mistral") or any DeepEvalBaseLLM
# subclass, or remove the `model` argument entirely to fall back to the configured
# OpenAI model.
model = OllamaModel(model="llama3.2")

styling_config = StylingConfig(
    task=(
        "Assess the risk and affordability of a personal loan application. "
        "The agent must use the appropriate tools (credit check, fraud screening, "
        "employment verification or bank statement analysis, collateral valuation "
        "if applicable, and affordability assessment) before producing a final "
        "APPROVE or REJECT recommendation with full justification."
    ),
    scenario=(
        "A loan underwriting agent inside a BPMN ad-hoc subprocess. "
        "Applicants may be employed or self-employed, may or may not offer collateral, "
        "and request loan amounts between £10,000 and £150,000 for purposes such as "
        "home improvement, debt consolidation, vehicle purchase, or business investment. "
        "Risk factors include credit score band (LOW/MEDIUM/HIGH), fraud risk score "
        "(0-100), debt-to-income ratio, and income verification outcome."
    ),
    input_format=(
        "A natural language goal statement for the loan underwriting agent describing "
        "the applicant's type (EMPLOYED or SELF_EMPLOYED), requested loan amount, "
        "loan purpose, and whether collateral is offered. "
        "Example: 'Perform a complete loan risk assessment for an employed applicant "
        "requesting £50,000 for home improvement. No collateral has been offered.'"
    ),
    expected_output_format=(
        "A structured assessment summary beginning with APPROVE or REJECT (in capitals), "
        "followed by a concise justification that cites the specific evidence gathered: "
        "credit score and risk band, fraud risk score, income verification outcome, "
        "debt-to-income ratio, collateral value if applicable, and affordability result. "
        "End with an explicit 'Recommendation: APPROVE/REJECT the loan application.' line."
    ),
)

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def main() -> None:
    synthesizer = Synthesizer(model=model, styling_config=styling_config)

    print(f"Generating {NUM_GOLDENS} goldens for the loan assessment domain …")
    synthesizer.generate_goldens_from_scratch(
        num_goldens=NUM_GOLDENS,
        include_expected_output=True,
    )

    synthesizer.save_as(
        file_type="json",
        directory=str(OUTPUT_DIR),
        file_name="goldens",
    )
    print(f"Saved to {OUTPUT_DIR / 'goldens.json'}")
    print(f"Generated {len(synthesizer.synthetic_goldens)} goldens.")


if __name__ == "__main__":
    main()
