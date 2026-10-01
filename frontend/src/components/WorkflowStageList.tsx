import type { WorkflowStage } from '../api'

interface WorkflowStageListProps {
  stages: WorkflowStage[]
}

interface StageRowProps {
  stage: WorkflowStage
  depth: number
}

function StageStatus({ done }: { done: boolean }) {
  return done ? (
    <span className="stage-table-done" aria-hidden="true">
      ✓
    </span>
  ) : (
    <span className="spinner" aria-hidden="true" />
  )
}

function StageRow({ stage, depth }: StageRowProps) {
  return (
    <>
      <tr className="stage-table-row">
        <td style={depth > 0 ? { paddingLeft: `${depth * 1.25}rem` } : undefined}>{stage.name}</td>
        <td>
          <StageStatus done={Boolean(stage.endTime)} />
        </td>
      </tr>
      {stage.children?.map((child) => (
        <StageRow key={child.activityId} stage={child} depth={depth + 1} />
      ))}
    </>
  )
}

function WorkflowStageList({ stages }: WorkflowStageListProps) {
  return (
    <table className="stage-table">
      <thead>
        <tr>
          <th>Stage</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {stages.map((stage) => (
          <StageRow key={stage.activityId} stage={stage} depth={0} />
        ))}
      </tbody>
    </table>
  )
}

export default WorkflowStageList
