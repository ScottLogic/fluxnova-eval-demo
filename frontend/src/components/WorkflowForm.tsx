import { useState, type FormEvent } from 'react'
import type { WorkflowVariables } from '../api'
import { fieldInfo } from '../lib/workflowFields'
import Toggle from './Toggle'

interface WorkflowFormProps {
  defaults: WorkflowVariables | null
  submitting: boolean
  onSubmit: (values: WorkflowVariables) => void
}

// Not applicant-facing inputs, so not user-editable here:
// - skipEvalServiceWorker is already controlled by the "Eval service worker"
//   toggle in the Evals section above (see EvalToggles.tsx / WorkflowPage's
//   handleSubmit, which always overrides this value on submit) — editing it
//   here too would be redundant and misleading, since this form's own copy is
//   never actually sent.
// - aiRiskScore / approvalDecision are just starting values for BPMN gateway
//   conditions (Gateway_4 "Risk Approved?" / Gateway_5 "Manual Review
//   Required?"), not data about the applicant — they get set for real
//   partway through the run, not by the person triggering it.
const HIDDEN_FIELDS = new Set(['skipEvalServiceWorker', 'aiRiskScore', 'approvalDecision'])

function WorkflowForm({ defaults, submitting, onSubmit }: WorkflowFormProps) {
  const [values, setValues] = useState<WorkflowVariables>({})
  // Adjust state during render when `defaults` first arrives, rather than in a
  // useEffect — see https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [appliedDefaults, setAppliedDefaults] = useState<WorkflowVariables | null>(null)
  if (defaults && defaults !== appliedDefaults) {
    setAppliedDefaults(defaults)
    setValues(defaults)
  }

  function setField(name: string, value: string | number | boolean) {
    setValues((current) => ({ ...current, [name]: value }))
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSubmit(values)
  }

  if (!defaults) {
    return <p className="hint">Loading form defaults…</p>
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      <div className="form-group-row">
        {Object.entries(values)
          .filter(([name]) => !HIDDEN_FIELDS.has(name))
          .map(([name, value]) => {
            const { label, description } = fieldInfo(name)
            if (typeof value === 'boolean') {
              return (
                <Toggle
                  key={name}
                  label={label}
                  title={description}
                  checked={value}
                  onChange={(checked) => setField(name, checked)}
                />
              )
            }
            return (
              <label key={name} className="field" title={description || undefined}>
                <span>{label}</span>
                {typeof value === 'number' ? (
                  <input
                    type="number"
                    value={value}
                    onChange={(event) => setField(name, Number(event.target.value))}
                  />
                ) : (
                  <input
                    type="text"
                    value={value}
                    onChange={(event) => setField(name, event.target.value)}
                  />
                )}
              </label>
            )
          })}
      </div>

      <div className="actions">
        <button type="submit" className="btn primary" disabled={submitting}>
          {submitting ? 'Starting…' : 'Start run'}
        </button>
      </div>
    </form>
  )
}

export default WorkflowForm
