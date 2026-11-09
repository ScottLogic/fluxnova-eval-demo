import { useEffect, useState } from 'react'
import { fetchEvalDefinitions, type GuardrailConfig } from '../api'
import { useEvalSettings } from '../useEvalSettings'
import { formatPercent } from './GuardrailThresholds'

interface GuardrailSettingsProps {
  guardrail: GuardrailConfig | null
}

// Lets the user set the guardrail's settings for the next run. The values are
// sent as the evalMinScore / evalRequiredScorers / evalSampleRate /
// forceReviewEveryN process variables, which the BPMN task's inputs use in
// place of their defaults.
function GuardrailSettings({ guardrail }: GuardrailSettingsProps) {
  const {
    skipEvalServiceWorker,
    minScore,
    setMinScore,
    requiredScorers,
    setRequiredScorers,
    sampleRate,
    setSampleRate,
    forceReviewEveryN,
    setForceReviewEveryN,
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
  const effectiveRate = sampleRate ?? guardrail.sampleRate ?? 1
  const effectiveEveryN = forceReviewEveryN ?? guardrail.forceReviewEveryN ?? 0
  const customised =
    minScore !== null || requiredScorers !== null || sampleRate !== null || forceReviewEveryN !== null

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
      <legend className="sample-preview-label">Guardrail settings for the next run</legend>
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
      <label className="field guardrail-min-score">
        <span>
          Sample rate: score {formatPercent(effectiveRate)} of runs
          {effectiveRate < 1 && ' (the rest carry on without scoring or review)'}
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={effectiveRate}
          onChange={(event) => setSampleRate(Number(event.target.value))}
        />
      </label>
      <label className="field guardrail-every-n">
        <span>
          Review every Nth run whatever its score:{' '}
          {effectiveEveryN > 0 ? `every ${ordinal(effectiveEveryN)} run` : 'off'}
        </span>
        <input
          type="number"
          min={0}
          step={1}
          value={effectiveEveryN}
          onChange={(event) => {
            const value = Math.max(0, Math.floor(Number(event.target.value) || 0))
            setForceReviewEveryN(value)
          }}
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
        BPMN defaults: minimum {guardrail.minScore === null ? 'invalid' : formatPercent(guardrail.minScore)},
        required {guardrail.requiredScorers.length > 0 ? guardrail.requiredScorers.join(', ') : 'none'},
        sample rate {guardrail.sampleRate === null ? 'invalid' : formatPercent(guardrail.sampleRate)}, every-Nth
        review {guardrail.forceReviewEveryN ? `every ${ordinal(guardrail.forceReviewEveryN)} run` : 'off'}.
        {customised && (
          <>
            {' '}
            <button
              type="button"
              className="btn ghost btn-small"
              onClick={() => {
                setMinScore(null)
                setRequiredScorers(null)
                setSampleRate(null)
                setForceReviewEveryN(null)
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

function ordinal(n: number): string {
  const tens = n % 100
  const suffix =
    tens >= 11 && tens <= 13 ? 'th' : n % 10 === 1 ? 'st' : n % 10 === 2 ? 'nd' : n % 10 === 3 ? 'rd' : 'th'
  return `${n}${suffix}`
}

export default GuardrailSettings
