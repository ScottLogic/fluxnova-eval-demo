import type { WorkflowVariables } from '../api'

interface WorkflowVariablesListProps {
  variables: WorkflowVariables | undefined
}

function WorkflowVariablesList({ variables }: WorkflowVariablesListProps) {
  const visibleVariables = Object.entries(variables ?? {}).filter(
    ([name]) => !name.startsWith('_agent'),
  )
  if (visibleVariables.length === 0) {
    return null
  }

  return (
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
  )
}

export default WorkflowVariablesList
