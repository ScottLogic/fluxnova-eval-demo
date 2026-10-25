import type { WorkflowRunStatus } from '../api'
import { currentStagePath } from '../lib/workflowStages'

interface WorkflowCurrentStageProps {
  deploying: boolean
  run: WorkflowRunStatus | null
}

function WorkflowCurrentStage({ deploying, run }: WorkflowCurrentStageProps) {
  if (!deploying && !run) {
    return null
  }

  const running = deploying || run?.status === 'active'
  const path = run ? currentStagePath(run.stages ?? []) : null
  const label = deploying ? 'Deploying and initiating BPMN' : (path?.join(' → ') ?? 'Starting…')

  return (
    <div className="current-stage">
      {running ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <span className="stage-table-done" aria-hidden="true">
          ✓
        </span>
      )}
      <span className="current-stage-label">{label}</span>
      {run && <span className={`status-badge status-${run.status}`}>{run.status}</span>}
    </div>
  )
}

export default WorkflowCurrentStage
