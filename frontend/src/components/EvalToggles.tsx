import { useEvalSettings } from '../useEvalSettings'
import Toggle from './Toggle'

function EvalToggles() {
  const { skipEvalServiceWorker, setSkipEvalServiceWorker } = useEvalSettings()

  return (
    <div className="form-group-row">
      <Toggle
        label="Eval service worker"
        title="When disabled, the run skips the blocking guardrail Eval service task. The non-blocking async eval still runs."
        checked={!skipEvalServiceWorker}
        onChange={(checked) => setSkipEvalServiceWorker(!checked)}
      />
    </div>
  )
}

export default EvalToggles
