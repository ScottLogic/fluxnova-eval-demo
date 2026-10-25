const GRAFANA_URL = 'http://localhost:3000'
const MLFLOW_URL = 'http://localhost:5000'

const METRICS: Array<{
    metric: string
    instrument: string
    unit: string
    emittedPer: string
    attributes: string
    details: string
}> = [
    {
        metric: 'gen_ai.client.token.usage',
        instrument: 'histogram',
        unit: '{token}',
        emittedPer: 'chat + invoke_agent',
        attributes: 'gen_ai.operation.name, gen_ai.token.type, gen_ai.provider.name, gen_ai.request.model',
        details: 'Histogram of token consumption. Filter by gen_ai.token.type to separate input from output tokens.'
    },
    {
        metric: 'gen_ai.client.operation.duration',
        instrument: 'histogram',
        unit: 'seconds',
        emittedPer: 'chat, execute_tool, invoke_agent',
        attributes:
            'gen_ai.operation.name, gen_ai.provider.name, gen_ai.request.model, gen_ai.tool.name, error.type',
        details: 'Histogram of LLM call latencies. Filter by gen_ai.request.model to compare models.'
    },
    {
        metric: 'gen_ai.invoke_agent.duration',
        instrument: 'histogram',
        unit: 'seconds',
        emittedPer: 'subprocess execution',
        attributes: 'gen_ai.agent.name, gen_ai.request.model',
        details: 'Measures the end-to-end latency of a single, in-process AI agent invocation'
    },
    {
        metric: 'gen_ai.invoke_agent.inference_calls',
        instrument: 'histogram',
        unit: '{inference_call}',
        emittedPer: 'subprocess execution',
        attributes: 'gen_ai.agent.name',
        details: 'This metric is a counter that tracks the total number of underlying Large Language Model (LLM) inference calls made during a single execution of an AI agent (invoke_agent operation)'
    },
    {
        metric: 'gen_ai.invoke_agent.tool_calls',
        instrument: 'histogram',
        unit: '{tool_call}',
        emittedPer: 'subprocess execution',
        attributes: 'gen_ai.agent.name',
        details: 'Tracks how many tool calls an AI agent executes during a single agent run'
    },
    {
        metric: 'gen_ai.execute_tool.duration',
        instrument: 'histogram',
        unit: 'seconds',
        emittedPer: 'tool call',
        attributes: 'gen_ai.tool.name, gen_ai.tool.call.id, gen_ai.agent.name, error.type',
        details: 'Measures the duration of a single AI agent tool execution'
    },
]

const SIGNALS: Array<{
    operation: string
    metrics: string
    span: string
}> = [
    {
        operation: "invoke_agent",
        metrics: "gen_ai.client.token.usage, gen_ai.client.operation.duration, gen_ai.invoke_agent.duration, gen_ai.invoke_agent.inference_calls, gen_ai.invoke_agent.tool_calls",
        span: "gen_ai.invoke_agent.internal"
    },
    {
        operation: "chat",
        metrics: "gen_ai.client.token.usage, gen_ai.client.operation.duration",
        span: "gen_ai.inference.client"
    },
    {
        operation: "execute_tool",
        metrics: "gen_ai.client.operation.duration, gen_ai.execute_tool.duration",
        span: "gen_ai.execute_tool.internal"
    }
]

function TelemetryPage() {
    return (
        <section className="panel">
            <div className="panel-head">
                <p className="eyebrow">Telemetry</p>
                <h1>Metrics &amp; tracing</h1>
                <p className="panel-copy">
                    The Fluxnova engine instruments each ad-hoc agent subprocess with <a target="_blank"
                                                                                         href="https://github.com/open-telemetry/semantic-conventions-genai#-opentelemetry-genai-semantic-conventions">OpenTelemetry</a> signals
                    in the <code>gen_ai.*</code> namespace, following the OpenTelemetry GenAI semantic
                    conventions. The engine emits OTLP only — the OTel Collector fans it out to MLflow
                    (traces) and Prometheus (metrics, dashboarded in Grafana).
                </p>
            </div>

            <div className="actions">
                <a className="btn primary" href={GRAFANA_URL} target="_blank" rel="noreferrer">
                    Open Grafana
                </a>
                <a className="btn ghost" href={MLFLOW_URL} target="_blank" rel="noreferrer">
                    Open MLflow dashboard
                </a>
            </div>

            <div>
                <p className="sample-preview-label">Signals</p>
                <div className="metrics-table-wrap">
                    <table className="metrics-table">
                        <thead>
                        <tr>
                            <th>Operation</th>
                            <th>Metric(s)</th>
                            <th>Span</th>
                        </tr>
                        </thead>
                        <tbody>
                        {SIGNALS.map((row) => (
                            <tr key={row.operation}>
                                <td>{row.operation}</td>
                                <td>{row.metrics.split(",").map(m =>
                                    (<div key={m}>{m}<br></br></div>))}</td>
                                <td>{row.span}</td>
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </div>
            </div>

            <div>
                <p className="sample-preview-label">Metrics exported</p>
                <div className="metrics-table-wrap">
                    <table className="metrics-table">
                        <thead>
                        <tr>
                            <th>Metric</th>
                            <th>Instrument</th>
                            <th>Unit</th>
                            <th>Emitted per</th>
                            <th>Key attributes</th>
                            <th>Details</th>
                        </tr>
                        </thead>
                        <tbody>
                        {METRICS.map((row) => (
                            <tr key={row.metric}>
                                <td>{row.metric}</td>
                                <td>{row.instrument}</td>
                                <td>{row.unit}</td>
                                <td>{row.emittedPer}</td>
                                <td>{row.attributes.split(",").map(m =>
                                    (<div key={m}>{m}<br></br></div>))}
                                </td>
                                <td>{row.details}</td>
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </div>
            </div>

            <div>
                <p className="sample-preview-label">Trace shape</p>
                <p className="hint">
                    One subprocess execution drives three GenAI operations, forming a span tree per run which looks like:
                </p>
                <pre className="test-run-output">
          {`invoke_agent {gen_ai.agent.name}     type gen_ai.invoke_agent.internal     (INTERNAL)
chat {gen_ai.request.model}          type gen_ai.inference.client          (CLIENT)
execute_tool {gen_ai.tool.name}      type gen_ai.execute_tool.internal     (INTERNAL)
chat {gen_ai.request.model}          type gen_ai.inference.client          (CLIENT)
...`}
        </pre>
            </div>
        </section>
    )
}

export default TelemetryPage
