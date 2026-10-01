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

  return (
    <div>
      <p className="sample-preview-label">Agent decision</p>
      <p>{message}</p>
    </div>
  )
}

export default AgentDecision
