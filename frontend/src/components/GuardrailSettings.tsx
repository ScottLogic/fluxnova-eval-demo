import { useEffect, useState } from 'react'
import { fetchEvalDefinitions, type GuardrailConfig } from '../api'
import { useEvalSettings } from '../useEvalSettings'
import { formatPercent } from './GuardrailThresholds'

interface GuardrailSettingsProps {
  guardrail: GuardrailConfig | null
}

// Lets the user set the guardrail's pass thresholds for the next run. The
// values are sent as the evalMinScore / evalRequiredScorers process variables,
// which the BPMN task's inputs use in place of their defaults.
function GuardrailSettings({ guardrail }: GuardrailSettingsProps) {
  const {
    skipEvalServiceWorker,
    minScore,
    setMinScore,
    requiredScorers,
    setRequiredScorers,
  } = useEvalSettings()
  const [scorerNames, setScorerNames] = useState<string[]>([])
  const [scorersError, setScorersError] = useState<string | null>(null)

  useEffect(() => {
    fetchEvalDefinitions()
      .then((definitions) =>
        setScorerNames(
          definitions.scorers.filter((s) => s.usedInEvalServiceWorker).map((s) => s.name),
        ),
      )
      .catch((err: unknown) =>
        setScorersError(err instanceof Error ? err.message : 'Failed to load scorers'),
      )
  }, [])

  if (!guardrail || !guardrail.overridable) {
    return null
  }

  const effectiveMin = minScore ?? guardrail.minScore ?? 1
  const effectiveRequired = requiredScorers ?? guardrail.requiredScorers
  const customised = minScore !== null || requiredScorers !== null

  function toggleRequired(name: string, checked: boolean) {
    const next = new Set(effectiveRequired)
    if (checked) {
      next.add(name)
    } else {
      next.delete(name)
    }
    // Keep the table's order, and never drop a name that isn't in the loaded
    // scorer list (e.g. a BPMN default, or before the list has loaded).
    setRequiredScorers([
      ...scorerNames.filter((scorer) => next.has(scorer)),
      ...[...next].filter((scorer) => !scorerNames.includes(scorer)),
    ])
  }

  return (
    <fieldset className="guardrail-settings" disabled={skipEvalServiceWorker}>
      <legend className="sample-preview-label">Guardrail thresholds for the next run</legend>
      {skipEvalServiceWorker && (
        <p className="hint">The guardrail is off for the next run, so these don't apply.</p>
      )}
      <label className="field guardrail-min-score">
        <span>
          Minimum score: {formatPercent(effectiveMin)} of applicable scorers must pass
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={effectiveMin}
          onChange={(event) => setMinScore(Number(event.target.value))}
        />
      </label>
      <div className="field">
        <span>Required scorers (must pass whatever the score)</span>
        {scorersError && <p className="hint danger">{scorersError}</p>}
        <div className="guardrail-scorer-list">
          {scorerNames.map((name) => (
            <label key={name} className="guardrail-scorer">
              <input
                type="checkbox"
                checked={effectiveRequired.includes(name)}
                onChange={(event) => toggleRequired(name, event.target.checked)}
              />
              <code>{name}</code>
            </label>
          ))}
        </div>
      </div>
      <p className="hint">
        BPMN default: {guardrail.minScore === null ? 'invalid' : formatPercent(guardrail.minScore)},
        required {guardrail.requiredScorers.length > 0 ? guardrail.requiredScorers.join(', ') : 'none'}.
        {customised && (
          <>
            {' '}
            <button
              type="button"
              className="btn ghost btn-small"
              onClick={() => {
                setMinScore(null)
                setRequiredScorers(null)
              }}
            >
              Reset to BPMN defaults
            </button>
          </>
        )}
      </p>
    </fieldset>
  )
}

export default GuardrailSettings
