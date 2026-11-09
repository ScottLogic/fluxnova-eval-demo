import type { WorkflowVariables } from '../api'

// Fluxnova's welcome page links to Tasklist, where the review form opens.
const FLUXNOVA_UI_URL = 'http://localhost:8080/fluxnova-welcome/index.html'

const REASON_LABELS: Record<string, string> = {
  FAILED_EVAL: 'the guardrail evaluation failed',
  FORCED_EVERY_N: 'every Nth run is reviewed whatever its score',
}

function reviewReasons(variables: WorkflowVariables): string {
  const raw = typeof variables.reviewReason === 'string' ? variables.reviewReason : ''
  const reasons = raw
    .split(',')
    .map((r) => r.trim())
    .filter(Boolean)
    .map((r) => REASON_LABELS[r] ?? r)
  const run = typeof variables.runNumber === 'number' ? ` (run ${variables.runNumber})` : ''
  return reasons.length > 0 ? `Sent for review because ${reasons.join(', and ')}${run}.` : ''
}

const OUTCOME_LABELS: Record<string, string> = {
  APPROVE: "Approved: kept the agent's decision",
  AMEND: "Amended the agent's decision",
  REJECT: 'Rejected the assessment: loan declined',
}

interface ReviewResultProps {
  variables: WorkflowVariables | undefined
  active: boolean
}

// The human review the guardrail asked for (failed evaluation and/or every-Nth
// run): waiting for a reviewer in Fluxnova Tasklist, or the reviewer's outcome
// once the task is completed.
function ReviewResult({ variables, active }: ReviewResultProps) {
  // reviewRequired is set by the guardrail; older runs only have evalPassed.
  const required =
    typeof variables?.reviewRequired === 'boolean'
      ? variables.reviewRequired
      : variables?.evalPassed === false
  if (!variables || !required) {
    return null
  }
  const reason = reviewReasons(variables)

  const outcome = typeof variables.reviewOutcome === 'string' ? variables.reviewOutcome : null
  if (!outcome) {
    if (!active) {
      return null
    }
    return (
      <div className="review-result">
        <p className="sample-preview-label">Human review</p>
        <p>
          <span className="status-badge status-active">waiting for a reviewer</span>
        </p>
        {reason && <p className="hint">{reason}</p>}
        <p className="hint">
          Open Fluxnova Tasklist (login <code>demo</code> / <code>demo</code>) and complete the{' '}
          <em>Human: Risk Assessment Review</em> task. Its form shows why the run is being reviewed, the agent's
          assessment, the evidence and the guardrail result. Choose to approve the agent's decision, amend it to approve or decline, or reject the
          assessment (which declines the loan); the loan then follows your decision.
        </p>
        <a className="btn ghost" href={FLUXNOVA_UI_URL} target="_blank" rel="noreferrer">
          Open Fluxnova Tasklist
        </a>
      </div>
    )
  }

  const decision = typeof variables.reviewDecision === 'string' ? variables.reviewDecision : null
  const comment = typeof variables.reviewComment === 'string' ? variables.reviewComment : null
  const agentDecision = typeof variables.agentDecision === 'string' ? variables.agentDecision : null

  return (
    <div className="review-result">
      <p className="sample-preview-label">Human review</p>
      {reason && <p className="hint">{reason}</p>}
      <dl className="result-grid">
        <div>
          <dt>Outcome</dt>
          <dd>
            {OUTCOME_LABELS[outcome] ?? outcome}
            {outcome === 'AMEND' && typeof variables.amendedDecision === 'string' && ` to ${variables.amendedDecision}`}
          </dd>
        </div>
        <div>
          <dt>Final decision</dt>
          <dd>
            {decision ?? 'unknown'}
            {agentDecision && decision !== agentDecision && ` (agent said ${agentDecision})`}
          </dd>
        </div>
        <div>
          <dt>Reviewer's comment</dt>
          <dd>{comment || 'none'}</dd>
        </div>
      </dl>
    </div>
  )
}

export default ReviewResult
