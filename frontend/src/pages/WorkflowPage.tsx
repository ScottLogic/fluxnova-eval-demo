import { useEffect } from 'react'
import type { WorkflowVariables } from '../api'
import EvalToggles from '../components/EvalToggles'
import WorkflowForm from '../components/WorkflowForm'
import WorkflowRunStatus from '../components/WorkflowRunStatus'
import { useEvalSettings } from '../useEvalSettings'
import { useWorkflowStore } from '../store/workflowStore'

function WorkflowPage() {
  const { skipEvalServiceWorker } = useEvalSettings()
  const defaults = useWorkflowStore((state) => state.defaults)
  const configError = useWorkflowStore((state) => state.configError)
  const run = useWorkflowStore((state) => state.run)
  const runError = useWorkflowStore((state) => state.runError)
  const submitting = useWorkflowStore((state) => state.submitting)
  const loadConfig = useWorkflowStore((state) => state.loadConfig)
  const startRun = useWorkflowStore((state) => state.startRun)

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  function handleSubmit(values: WorkflowVariables) {
    startRun({ ...values, skipEvalServiceWorker })
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <p className="eyebrow">Workflow</p>
        <h1>Workflow run</h1>
        <p className="panel-copy">
          Trigger a run of the BPMN workflow and follow its progress. Use the defaults, or edit them before starting a run.
        </p>
      </div>

      <div>
        <p className="sample-preview-label">Evals</p>
        <p className="hint">
          Auto-eval takes effect immediately for all traces; eval service worker applies to the
          next run started below.
        </p>
        <EvalToggles />
      </div>

      {configError && <p className="hint danger">{configError}</p>}
      <WorkflowForm defaults={defaults} submitting={submitting} onSubmit={handleSubmit} />

      {runError && <p className="hint danger">{runError}</p>}
      {run && <WorkflowRunStatus run={run} />}
    </section>
  )
}

export default WorkflowPage
