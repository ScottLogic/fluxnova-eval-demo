import type { GuardrailConfig, WorkflowVariables } from '../api'
import { formatPercent } from './GuardrailThresholds'

interface GuardrailResultProps {
  variables: WorkflowVariables | undefined
  guardrail: GuardrailConfig | null
  skipped: boolean
}

// Shows the blocking guardrail's verdict for a run, from the variables the
// eval-service-worker writes back: evalPassed, evalScore, evalFailedScorers
// and evalRationale.
function GuardrailResult({ variables, guardrail, skipped }: GuardrailResultProps) {
  const passed = variables?.evalPassed
  if (variables?.evalSampled === false) {
    return (
      <div>
        <p className="sample-preview-label">Guardrail</p>
        <p>
          <span className="status-badge status-warn">not sampled</span>
        </p>
        <p className="hint">
          This run wasn't in the guardrail's sample (evalSampleRate), so it wasn't scored and carried on without
          review. The async eval still scores every run.
        </p>
      </div>
    )
  }
  if (typeof passed !== 'boolean') {
    if (!skipped) {
      return null
    }
    return (
      <div>
        <p className="sample-preview-label">Guardrail</p>
        <p className="hint">Skipped for this run, so the agent's decision went straight to the risk gateway.</p>
      </div>
    )
  }

  const score = typeof variables?.evalScore === 'number' ? variables.evalScore : null
  const failed = String(variables?.evalFailedScorers ?? '')
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)
  const rationale = typeof variables?.evalRationale === 'string' ? variables.evalRationale : null
  // Thresholds this run was started with, falling back to the BPMN defaults.
  const runMin = typeof variables?.evalMinScore === 'number' ? variables.evalMinScore : null
  const minScore = runMin ?? guardrail?.minScore ?? null
  const required =
    typeof variables?.evalRequiredScorers === 'string'
      ? variables.evalRequiredScorers.split(',').map((n) => n.trim()).filter(Boolean)
      : (guardrail?.requiredScorers ?? [])

  return (
    <div className="guardrail-result">
      <p className="sample-preview-label">Guardrail</p>
      <p>
        <span className={`status-badge ${passed ? 'status-pass' : 'status-fail'}`}>
          {passed ? 'passed' : 'failed: sent to human review'}
        </span>
      </p>
      <dl className="result-grid">
        {score !== null && (
          <div>
            <dt>Score</dt>
            <dd>
              {formatPercent(score)} of applicable scorers passed
              {minScore !== null && ` (minimum ${formatPercent(minScore)})`}
            </dd>
          </div>
        )}
        <div>
          <dt>Failed scorers</dt>
          <dd>{failed.length > 0 ? failed.join(', ') : 'none'}</dd>
        </div>
        <div>
          <dt>Required scorers</dt>
          <dd>{required.length > 0 ? required.join(', ') : 'none'}</dd>
        </div>
      </dl>
      {rationale && <p className="hint">{rationale}</p>}
    </div>
  )
}

export default GuardrailResult
