import type { WorkflowRunStatus as WorkflowRunStatusData } from '../api'

interface WorkflowRunStatusProps {
  run: WorkflowRunStatusData
}

interface ConversationEntry {
  role: string
  content: string | null
}

function finalAgentMessage(variables: Record<string, unknown> | undefined): string | null {
  const raw = variables?.['_agentConversationHistory']
  if (typeof raw !== 'string') {
    return null
  }
  try {
    const history = JSON.parse(raw) as ConversationEntry[]
    const lastAssistantMessage = [...history].reverse().find(
      (entry) => entry.role === 'ASSISTANT' && entry.content,
    )
    return lastAssistantMessage?.content ?? null
  } catch {
    return null
  }
}

function WorkflowRunStatus({ run }: WorkflowRunStatusProps) {
  const message = finalAgentMessage(run.variables)
  const visibleVariables = Object.entries(run.variables ?? {}).filter(
    ([name]) => !name.startsWith('_agent'),
  )

  return (
    <div className="panel">
      <div className="panel-head-row">
        <span>Instance: {run.instanceId}</span>
        <span className={`status-badge status-${run.status}`}>{run.status}</span>
      </div>

      {message && (
        <div>
          <p className="sample-preview-label">Agent decision</p>
          <p>{message}</p>
        </div>
      )}

      {visibleVariables.length > 0 && (
        <div>
          <p className="sample-preview-label">Variables</p>
          <dl className="result-grid">
            {visibleVariables.map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}

export default WorkflowRunStatus
