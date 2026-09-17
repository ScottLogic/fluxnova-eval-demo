const GRAFANA_URL = 'http://localhost:3000'
const MLFLOW_URL = 'http://localhost:5000'

const METRICS: Array<{
  metric: string
  instrument: string
  unit: string
  emittedPer: string
  attributes: string
}> = [
  {
    metric: 'gen_ai.client.token.usage',
    instrument: 'histogram',
    unit: '{token}',
    emittedPer: 'chat + invoke_agent',
    attributes: 'gen_ai.operation.name, gen_ai.token.type, gen_ai.provider.name, gen_ai.request.model',
  },
  {
    metric: 'gen_ai.client.operation.duration',
    instrument: 'histogram',
    unit: 'seconds',
    emittedPer: 'chat, execute_tool, invoke_agent',
    attributes:
      'gen_ai.operation.name, gen_ai.provider.name, gen_ai.request.model, gen_ai.tool.name, error.type',
  },
  {
    metric: 'gen_ai.invoke_agent.duration',
    instrument: 'histogram',
    unit: 'seconds',
    emittedPer: 'subprocess execution',
    attributes: 'gen_ai.agent.name, gen_ai.request.model',
  },
  {
    metric: 'gen_ai.invoke_agent.inference_calls',
    instrument: 'histogram',
    unit: '{inference_call}',
    emittedPer: 'subprocess execution',
    attributes: 'gen_ai.agent.name',
  },
  {
    metric: 'gen_ai.invoke_agent.tool_calls',
    instrument: 'histogram',
    unit: '{tool_call}',
    emittedPer: 'subprocess execution',
    attributes: 'gen_ai.agent.name',
  },
  {
    metric: 'gen_ai.execute_tool.duration',
    instrument: 'histogram',
    unit: 'seconds',
    emittedPer: 'tool call',
    attributes: 'gen_ai.tool.name, gen_ai.tool.call.id, gen_ai.agent.name, error.type',
  },
]

function TelemetryPage() {
  return (
    <section className="panel">
      <div className="panel-head">
        <p className="eyebrow">Telemetry</p>
        <h1>Metrics &amp; tracing</h1>
        <p className="panel-copy">
          The Fluxnova engine instruments each ad-hoc agent subprocess with OpenTelemetry signals
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
              </tr>
            </thead>
            <tbody>
              {METRICS.map((row) => (
                <tr key={row.metric}>
                  <td>{row.metric}</td>
                  <td>{row.instrument}</td>
                  <td>{row.unit}</td>
                  <td>{row.emittedPer}</td>
                  <td>{row.attributes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <p className="sample-preview-label">Trace shape</p>
        <p className="hint">
          One subprocess execution drives three GenAI operations, forming this span tree per run:
        </p>
        <pre className="test-run-output">
          {`invoke_agent {gen_ai.agent.name}     type gen_ai.invoke_agent.internal (INTERNAL)
  chat {gen_ai.request.model}        type gen_ai.inference.client       (CLIENT)
  execute_tool {gen_ai.tool.name}    type gen_ai.execute_tool.internal  (INTERNAL)
  ...`}
        </pre>
        <p className="hint">
          Prompt/response/tool content (<code>gen_ai.input.messages</code>,{' '}
          <code>gen_ai.output.messages</code>, etc.) is disabled by default since it may contain
          sensitive data.
        </p>
      </div>
    </section>
  )
}

export default TelemetryPage
