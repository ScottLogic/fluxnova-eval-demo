import type { WorkflowVariables } from '../api'

interface AgentDecisionProps {
  variables: WorkflowVariables | undefined
}

interface ConversationEntry {
  role: string
  content: string | null
}

function finalAgentMessage(variables: WorkflowVariables | undefined): string | null {
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

function AgentDecision({ variables }: AgentDecisionProps) {
  const message = finalAgentMessage(variables)
  if (!message) {
    return null
  }
  // agentDecision is recorded by the BPMN when the agent Call Activity ends
  // (APPROVE, REJECT or UNKNOWN), and drives "Risk Approved?" unless a reviewer
  // overrides it.
  const decision = typeof variables?.agentDecision === 'string' ? variables.agentDecision : null

  return (
    <div>
      <p className="sample-preview-label">Agent decision</p>
      {decision && (
        <p>
          <span
            className={`status-badge ${decision === 'APPROVE' ? 'status-pass' : decision === 'REJECT' ? 'status-fail' : 'status-warn'}`}
          >
            {decision}
          </span>
        </p>
      )}
      <p className="agent-decision-text">{message}</p>
    </div>
  )
}

export default AgentDecision
