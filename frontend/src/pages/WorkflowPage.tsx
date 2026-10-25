import { useEffect } from 'react'
import type { WorkflowVariables } from '../api'
import AgentConfigPanel from '../components/AgentConfigPanel'
import AgentDecision from '../components/AgentDecision'
import EvalToggles from '../components/EvalToggles'
import WorkflowCurrentStage from '../components/WorkflowCurrentStage'
import WorkflowForm from '../components/WorkflowForm'
import WorkflowProcessDiagram from '../components/WorkflowProcessDiagram'
import WorkflowStageList from '../components/WorkflowStageList'
import WorkflowVariablesList from '../components/WorkflowVariablesList'
import { useEvalSettings } from '../useEvalSettings'
import { useWorkflowStore } from '../store/workflowStore'

// Fluxnova's own UI, confirmed in local-dev/services/fluxnova-up.sh (which
// prints and auto-opens this exact URL). Base port from local-dev/.env's
// FLUXNOVA_PORT.
const FLUXNOVA_UI_URL = 'http://localhost:8080/fluxnova-welcome/index.html'

function WorkflowPage() {
  const { skipEvalServiceWorker } = useEvalSettings()
  const defaults = useWorkflowStore((state) => state.defaults)
  const agentConfig = useWorkflowStore((state) => state.agentConfig)
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

  // A run has been triggered at least once this session — show the Output
  // section from the moment Start run is clicked (so "Deploying and
  // initiating BPMN" appears immediately), through to however the run ends.
  // Starting another run replaces this immediately (the store clears `run`
  // synchronously in startRun), rather than blocking a new run.
  const showOutput = submitting || run !== null

  return (
    <section className="panel">
      <div className="panel-head">
        <p className="eyebrow">Workflow</p>
        <h1>Workflow run</h1>
        <p className="panel-copy">
          Trigger a run of the BPMN workflow and follow its progress. Use the defaults, or edit them before starting a run.
        </p>
      </div>

      <div className="finos-panel evals-section">
        <p className="sample-preview-label">Evals</p>
        <p className="hint">
          Auto-eval takes effect immediately for all traces; eval service worker applies to the
          next run started below.
        </p>
        <EvalToggles />
      </div>

      {configError && <p className="hint danger">{configError}</p>}
      <div className="workflow-section">
        <h2 className="workflow-section-heading">Inputs</h2>
        <div className="workflow-input-grid">
          <WorkflowForm defaults={defaults} submitting={submitting} onSubmit={handleSubmit} />
          <AgentConfigPanel agentConfig={agentConfig} />
        </div>
      </div>

      {runError && <p className="hint danger">{runError}</p>}
      {showOutput && (
        <div className="workflow-section workflow-output">
          <div className="panel-head-row">
            <h2 className="workflow-section-heading">Output</h2>
            <a className="btn ghost" href={FLUXNOVA_UI_URL} target="_blank" rel="noreferrer">
              Open Fluxnova monitoring
            </a>
          </div>
          <WorkflowCurrentStage deploying={submitting} run={run} />
          {run && <AgentDecision variables={run.variables} />}
          {run && (
            <details className="workflow-details">
              <summary>Show run details</summary>
              <WorkflowStageList stages={run.stages ?? []} />
              <WorkflowVariablesList variables={run.variables} />
            </details>
          )}
          {run && <WorkflowProcessDiagram stages={run.stages ?? []} />}
        </div>
      )}
    </section>
  )
}

export default WorkflowPage
