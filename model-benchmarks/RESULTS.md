# Local Model Benchmarks — Loan Assessment Tool-Calling

Comparison of small, locally-hosted (Ollama) LLMs on their ability to drive the
multi-step tool-calling loop in the Fluxnova **loan assessment** agentic process.

- **Date:** 2026-09-04
- **Benchmark:** `fluxnova-runner/config/loan-assesment.yml`
- **Runner:** `fluxnova-run fluxnova-runner/config/loan-assesment.yml --with-mock-workers`
- **Metrics source:** OpenTelemetry collector `gen_ai_*` metrics (`http://localhost:8889/metrics`), captured per run as JSON via `capture-metrics.sh`.
- **Hardware target:** Dell XPS laptop, CPU-only inference (no GPU offload), models run one at a time.

### Test machine

| Component | Detail |
|-----------|--------|
| Device | Dell XPS |
| CPU | 11th Gen Intel Core i7-1195G7 (4 cores / 8 threads @ 2.92 GHz) |
| Host RAM | 32 GB (24 GB allocated to WSL2) |
| OS | WSL2 (Windows Subsystem for Linux), kernel 6.18 |
| Ollama | CPU backend |

> **Note on wall times:** all runs are **CPU-only** on the machine above. The approximate
> wall times below are therefore hardware-dependent and would drop substantially on a
> machine with GPU offload or more/faster cores. Use them for *relative* comparison
> between models, not as absolute performance figures. The tool-call / inference-call /
> token counts, by contrast, are hardware-independent.

## The contenders

Five locally-hosted models were tested. All were run at **Q4_K_M** quantisation — this is the
default quant Ollama pulls when you run `ollama pull <model>` without specifying a tag, so every
model here was used exactly as a typical user would get it out of the box (no hand-picked quant).
Parameter counts below are the total weights; note that not all "parameters" are equal —
Gemma 4 E2B in particular is an *effective* 2B model, so raw parameter count alone is a poor
size comparison.

### qwen3.5:4b — Alibaba Qwen 3.5 (released Mar 2, 2026)
Dense 4.7B model, multimodal (text + image), with an optional thinking mode and a large
256K-token context window. The newest general-purpose contender and, per public tool-use
leaderboards, the Qwen lineage is consistently the strongest small-model function-caller.

### gemma4:e2b — Google Gemma 4, "Effective 2B" (released Apr 2, 2026)
The most nuanced entry. The "E" stands for **effective** parameters: it is a Mixture-of-Experts-style
edge model with **~2.3B effective parameters** (≈5.1B counting embeddings — which is the "5.1B"
Ollama reports). Designed specifically for on-device/edge use, multimodal, with a thinking mode
and 128K context. So although it reports the second-highest parameter count in this group, its
*active/effective* footprint is the smallest of the successful models — the reason it is fast
and light despite the 5.1B label.

### granite4:3b — IBM Granite 4.0 3B (released Oct 2, 2025)
Dense 3.4B, text-only, 128K context. IBM markets Granite 4 explicitly for **improved instruction
following and tool-calling** in enterprise applications, making it a natural candidate for this
kind of agentic workflow. Oldest of the three "modern" models here.

### llama3.1:8b — Meta Llama 3.1 8B (released Jul 23, 2024)
Dense 8.0B, text-only, 128K context. The **largest** model in the test by raw parameters.
Included because the project already used it (it was the BPMN's default agent model), and it
doubles as the "does bigger help?" control.

### llama3.2:3b — Meta Llama 3.2 3B (released Sep 25, 2024)
Dense 3.2B, text-only, 128K context. Meta's small-model release; its model card lists "tool use"
as a strength. Included as the direct small-model counterpart to llama3.1, and because it was
already present in the project.

## Scenario

A single applicant profile was used for every model:

| Variable | Value |
|----------|-------|
| `applicantType` | `EMPLOYED` |
| `hasCollateral` | `false` |
| `requestedAmount` | 50,000 |

**Expected tools (4):** Check Credit Score, Run Fraud Screening, Assess Affordability, Verify Employment.

**Tools that should _not_ fire:** Value Collateral (`hasCollateral=false`), Analyse Bank Statements (applicant is `EMPLOYED`).

The BPMN agent system prompt explicitly instructs the model to run **all** required
checks and not to stop after a single tool result.

## Results

| Model | Tool calls | Correct set? | Inference calls | Input tokens | Output tokens | Tool errors | Approx wall time |
|-------|:---------:|:------------:|:---------------:|:------------:|:-------------:|:-----------:|:----------------:|
| **qwen3.5:4b** | 4 | ✅ exact | **3** | 3,855 | 819 | 0 | ~1 min |
| gemma4:e2b | 4 | ✅ exact | 5 | 4,691 | 1,898 | 0 | ~4 min |
| granite4:3b | 5 | ⚠️ +1 spurious | 6 | 6,488 | 287 | 0 | ~2.5 min |
| llama3.1:8b | 1 | ❌ 1 of 4 | 2 | 1,370 | 84 | 0 | ~0.5 min |
| llama3.2:3b | 1 | ❌ 1 of 4 | 2 | 1,366 | 61 | 0 | ~0.5 min |

### Ranking (tool-calling quality)

1. **qwen3.5:4b** — best. Exactly the 4 expected tools, fewest inference calls (batched the independent checks into parallel tool calls in a single turn), fastest, most token-efficient.
2. **gemma4:e2b** — correct tool set, but more verbose and slowest.
3. **granite4:3b** — called all 4 expected tools **plus** a spurious `Value Collateral` (ignored the `hasCollateral` condition).
4. **llama3.1:8b** — **failed**: called only 1 of 4 tools then stopped.
5. **llama3.2:3b** — **failed**: same failure mode as llama3.1:8b.

## Per-model notes

### qwen3.5:4b — WINNER
Exact 4-tool set, no extras. Only 3 inference calls because it emitted Credit Score,
Employment and Fraud checks as parallel tool calls in one turn (visible in the run log
as three tasks locked at the same timestamp). Fastest and most efficient.

### gemma4:e2b — solid but slower
Correct tool set, no spurious calls. Slower and wordier (5 inference calls, highest
output-token count), but reliably completes the full workflow. Validates the existing choice.

### granite4:3b — competent but over-eager
Ran all 4 expected tools **and** `Value Collateral`, which should not fire when
`hasCollateral=false`. An instruction-following miss (ignored the conditional), not a
crash — 0 tool errors. Did unnecessary work.

### llama3.1:8b / llama3.2:3b — FAILED
Both called **only** `Run Fraud Screening`, produced ~60–84 output tokens, and stopped —
never completing the multi-step loop despite the explicit system prompt. **0 tool errors**,
so this is a model *capability* gap (the model chooses to stop), not a runner/schema bug.
This reproduces the weak tool-calling behaviour observed on the team's llama-based setup.
The short wall time is misleading: these runs are fast only because they did almost no work.

## Interpretation

At this small scale, tool-calling ability tracks **model recency and training more than
raw parameter count**:

- **Model age is the strongest signal here.** The two oldest models (**llama3.1**,
  **llama3.2**, both from 2024 — roughly two years old as of this Sept 2026 benchmark) are
  exactly the two that fail the loop, while the three newer models from 2025–2026
  (**granite4**, **qwen3.5**, **gemma4**) all complete it. Newer models are
  better at agentic tool calling.
- **Size does not predict success.** The largest model, **llama3.1:8b (8.0B)**, fails,
  while the smaller **qwen3.5:4b**, **gemma4:e2b** and **granite4:3b** succeed. Bigger is
  not better for this task.
- **Recency isn't the _only_ factor.** **granite4:3b** is older than qwen3.5/gemma4 yet
  still completes the loop (it just over-calls), and Meta's own llama3.2 card lists "tool
  use" as a strength — yet it fails this multi-step loop. So the llama failures look
  **architectural/training-driven**, not merely a function of age.
- A timeout / partial run is **not** the cause — every run finished with 0 tool errors;
  the llama models simply stop calling tools early.

### Recommendation

For the "use a model better at tool calls" task, the data supports:

- **Adopt `qwen3.5:4b`** as the primary agent model (best tool-calling, fastest, most efficient), **or**
- **Keep `gemma4:e2b`** as a solid, proven alternative.
- **Move off `llama3.1` / `llama3.2`** — both fail to complete the tool loop in this workflow.

## Caveats

- **Single run, single scenario.** No variance runs and no `SELF_EMPLOYED` /
  `hasCollateral=true` profiles yet. Those would test the Bank-Statements-vs-Employment
  branch and whether granite's collateral over-call is ever correct.
- **No LLM-judge quality scores.** This benchmark intentionally captures only the
  behavioural tool-calling metrics from OpenTelemetry; the MLflow judge-scoring step was not
  run for these models, so the quality of the final APPROVE/REJECT recommendation is not
  scored here. This report covers **behavioural tool-calling metrics only**.

## Reproducing / data

- Raw per-model metric snapshots: ``
- Machine-readable summary: ``
- Capture script: `local-model-benchmarks/capture-metrics.sh <model> <before|after>`

To benchmark another model: edit the `model="..."` attribute in
`bpmn/loan-assesment.bpmn` (`<agent:config>`), then re-run `fluxnova-run` (auto-redeploys)
and `capture-metrics.sh`.
