import type { GuardrailConfig } from '../api'

interface GuardrailThresholdsProps {
  guardrail: GuardrailConfig | null
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

// Explains, in plain terms, when the blocking guardrail passes and where to
// change that: the thresholds are inputs on the BPMN task, not worker settings.
function GuardrailThresholds({ guardrail }: GuardrailThresholdsProps) {
  if (!guardrail) {
    return null
  }

  const { minScore, requiredScorers, taskName, configuredInBpmn } = guardrail
  const scoreRule =
    minScore === null
      ? 'evalMinScore on the BPMN task is not a valid number, so the guardrail will raise an incident.'
      : minScore >= 1
        ? 'every applicable scorer must pass'
        : `at least ${formatPercent(minScore)} of applicable scorers must pass`

  return (
    <div className="guardrail-thresholds">
      <p className="hint">
        <strong>Guardrail pass rule (BPMN default):</strong> {scoreRule}
        {minScore !== null && requiredScorers.length > 0 && (
          <>
            , and <code>{requiredScorers.join(', ')}</code> must pass whatever the score
          </>
        )}
        {minScore !== null && '.'} Scorers that don't apply to a run are left out. A failed run goes to
        the <em>Human: Risk Assessment Review</em> task.
        {guardrail.sampleRate !== null && guardrail.sampleRate < 1 &&
          ` Only ${formatPercent(guardrail.sampleRate)} of runs are scored; the rest carry on without review.`}
        {guardrail.forceReviewEveryN
          ? ` One run in every ${guardrail.forceReviewEveryN} also goes to review whatever its score.`
          : ''}
      </p>
      <p className="hint">
        {guardrail.overridable && 'Adjust the thresholds for the next run below. '}
        To change the default, edit the <em>{taskName}</em> task's inputs in the BPMN (Modeler → Inputs):{' '}
        <code>evalMinScore</code> (0–1), <code>evalRequiredScorers</code> (comma-separated scorer
        names, see the Evals tab), <code>evalSampleRate</code> (0–1) and <code>forceReviewEveryN</code> (0 = off). No worker change or restart is needed; the next deployment uses them.
        {!configuredInBpmn && ' This BPMN sets neither, so the defaults (every scorer must pass) apply.'}
      </p>
    </div>
  )
}

export default GuardrailThresholds
