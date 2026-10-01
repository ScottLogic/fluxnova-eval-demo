import type { WorkflowStage } from '../api'
import BpmnViewer from './BpmnViewer'

// The outer approval process — the top-level `stages` (not any stage's
// `children`) map directly onto this file's own element ids, including the
// Call Activity node itself (which stays "active" for the whole time the
// agent subprocess underneath it is running).
const PROCESS_BPMN_URL = '/bpmn/LoanApprovalProcess_AI.bpmn'

interface WorkflowProcessDiagramProps {
  stages: WorkflowStage[]
}

function WorkflowProcessDiagram({ stages }: WorkflowProcessDiagramProps) {
  if (stages.length === 0) {
    return null
  }

  const doneElementIds = stages.filter((stage) => stage.endTime).map((stage) => stage.activityId)
  const activeElementIds = stages.filter((stage) => !stage.endTime).map((stage) => stage.activityId)

  return (
    <div>
      <p className="sample-preview-label">Process diagram</p>
      <BpmnViewer xmlUrl={PROCESS_BPMN_URL} activeElementIds={activeElementIds} doneElementIds={doneElementIds} />
    </div>
  )
}

export default WorkflowProcessDiagram
