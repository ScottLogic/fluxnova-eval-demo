import type {AgentConfig} from '../api'

interface AgentConfigPanelProps {
    agentConfig: AgentConfig | null
}

function AgentConfigPanel({agentConfig}: AgentConfigPanelProps) {
    if (!agentConfig) {
        return null
    }

    return (
        <div className="finos-panel agent-config-panel">
            <p className="sample-preview-label">Agent configuration</p>
            <dl className="result-grid">
                <div>
                    <dt>Provider</dt>
                    <dd>{agentConfig.provider}</dd>
                </div>
                <div>
                    <dt>Model</dt>
                    <dd>{agentConfig.model}</dd>
                </div>
            </dl>
            <div>
                <p className="sample-preview-label">System prompt</p>
                <pre className="agent-config-prompt">{agentConfig.systemPrompt}</pre>
            </div>
        </div>
    )
}

export default AgentConfigPanel
