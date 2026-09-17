import { useEvalSettings } from '../useEvalSettings'

interface ToggleProps {
  label: string
  title: string
  checked: boolean
  onChange: (checked: boolean) => void
}

function Toggle({ label, title, checked, onChange }: ToggleProps) {
  return (
    <label className="toggle" title={title}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="toggle-track" aria-hidden="true" />
      <span className="toggle-label">{label}</span>
    </label>
  )
}

function EvalToggles() {
  const { skipEvalServiceWorker, setSkipEvalServiceWorker, autoEvalEnabled, setAutoEvalEnabled } =
    useEvalSettings()

  return (
    <div className="form-group-row">
      <Toggle
        label="Auto-eval (trace listener)"
        title="When enabled will automatically run evals aginst traces (non blocking)"
        checked={autoEvalEnabled}
        onChange={setAutoEvalEnabled}
      />

      <Toggle
        label="Eval service worker"
        title="When disbled will skip the eval service task from the bpmn"
        checked={!skipEvalServiceWorker}
        onChange={(checked) => setSkipEvalServiceWorker(!checked)}
      />
    </div>
  )
}

export default EvalToggles
