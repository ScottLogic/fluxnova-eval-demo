import { useEvalSettings } from '../useEvalSettings'
import AutoEvalToggle from './AutoEvalToggle'
import Toggle from './Toggle'

function EvalToggles() {
  const { skipEvalServiceWorker, setSkipEvalServiceWorker } = useEvalSettings()

  return (
    <div className="form-group-row">
      <AutoEvalToggle />

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
