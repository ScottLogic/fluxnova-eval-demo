import { useCallback, useEffect, useState } from 'react'
import {
  fetchWorkflowConfig,
  fetchWorkflowRun,
  startWorkflowRun,
  type WorkflowRunStatus as WorkflowRunStatusData,
  type WorkflowVariables,
} from '../api'
import EvalToggles from '../components/EvalToggles'
import WorkflowForm from '../components/WorkflowForm'
import WorkflowRunStatus from '../components/WorkflowRunStatus'
import { useEvalSettings } from '../useEvalSettings'

const POLL_MS = 2000

function WorkflowPage() {
  const { skipEvalServiceWorker } = useEvalSettings()
  const [defaults, setDefaults] = useState<WorkflowVariables | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [instanceId, setInstanceId] = useState<string | null>(null)
  const [run, setRun] = useState<WorkflowRunStatusData | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  const loadConfig = useCallback(() => {
    fetchWorkflowConfig()
      .then((config) => {
        setDefaults(config.variables)
        setConfigError(null)
      })
      .catch((error: unknown) => {
        setConfigError(error instanceof Error ? error.message : 'Failed to load defaults')
      })
  }, [])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (!instanceId) {
      return
    }
    let stopped = false
    let timer: number

    function poll() {
      fetchWorkflowRun(instanceId as string)
        .then((result) => {
          if (stopped) {
            return
          }
          setRun(result)
          if (result.status === 'active') {
            timer = window.setTimeout(poll, POLL_MS)
          }
        })
        .catch((error: unknown) => {
          if (stopped) {
            return
          }
          setRunError(error instanceof Error ? error.message : 'Failed to fetch run status')
        })
    }

    poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [instanceId])

  function handleSubmit(values: WorkflowVariables) {
    setSubmitting(true)
    setRunError(null)
    setRun(null)
    startWorkflowRun({ ...values, skipEvalServiceWorker })
      .then((payload) => setInstanceId(payload.instanceId))
      .catch((error: unknown) => {
        setRunError(error instanceof Error ? error.message : 'Failed to start run')
      })
      .finally(() => setSubmitting(false))
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
