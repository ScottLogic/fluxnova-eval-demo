import { useState, type FormEvent } from 'react'
import type { WorkflowVariables } from '../api'

interface WorkflowFormProps {
  defaults: WorkflowVariables | null
  submitting: boolean
  onSubmit: (values: WorkflowVariables) => void
}

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
        {Object.entries(values).map(([name, value]) => (
          <label key={name} className="field">
            <span>{name}</span>
            {typeof value === 'boolean' ? (
              <input
                type="checkbox"
                checked={value}
                onChange={(event) => setField(name, event.target.checked)}
              />
            ) : typeof value === 'number' ? (
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
        ))}
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
