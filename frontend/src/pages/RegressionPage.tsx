import { useCallback, useEffect, useState } from 'react'
import { fetchRegressionRun, fetchRegressionTests, startRegressionRun, type RegressionRunResult } from '../api'
import TestList from '../components/TestList'

const POLL_MS = 2000
// Default MLflow port from local-dev/.env's MLFLOW_PORT.
const MLFLOW_URL = 'http://localhost:5000'

function RegressionPage() {
  const [tests, setTests] = useState<string[] | null>(null)
  const [testsError, setTestsError] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<RegressionRunResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const loadTests = useCallback(() => {
    setTestsError(null)
    fetchRegressionTests()
      .then((payload) => setTests(payload.tests))
      .catch((error: unknown) => {
        setTestsError(error instanceof Error ? error.message : 'Failed to load tests')
      })
  }, [])

  useEffect(() => {
    loadTests()
  }, [loadTests])

  useEffect(() => {
    if (!runId) {
      return
    }
    let stopped = false
    let timer: number

    function poll() {
      fetchRegressionRun(runId as string)
        .then((result) => {
          if (stopped) {
            return
          }
          setRunResult(result)
          if (result.status === 'running') {
            timer = window.setTimeout(poll, POLL_MS)
          }
        })
        .catch((error: unknown) => {
          if (stopped) {
            return
          }
          setRunError(error instanceof Error ? error.message : 'Failed to fetch run status')
        })
    }

    poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [runId])

  function handleRun() {
    setStarting(true)
    setRunError(null)
    setRunResult(null)
    startRegressionRun()
      .then((payload) => setRunId(payload.runId))
      .catch((error: unknown) => {
        setRunError(error instanceof Error ? error.message : 'Failed to start run')
      })
      .finally(() => setStarting(false))
  }

  const running = starting || runResult?.status === 'running'

  return (
    <section className="panel">
      <div className="panel-head">
        <p className="eyebrow">Regression</p>
        <h1>Regression tests</h1>
        <p className="panel-copy">
          View available regression tests, trigger a run, and see results.
        </p>
      </div>

      <div className="actions">
        <button type="button" className="btn primary" onClick={handleRun} disabled={running}>
          {running ? 'Running…' : 'Run regression suite'}
        </button>
        <a className="btn ghost" href={MLFLOW_URL} target="_blank" rel="noreferrer">
          Open MLflow dashboard
        </a>
      </div>

      {testsError && <p className="hint danger">{testsError}</p>}
      {!tests && !testsError && <p className="hint">Loading tests…</p>}

      <TestList tests={tests} runResult={runResult} />

      {runError && <p className="hint danger">{runError}</p>}

      {runResult?.status === 'error' && (
        <div>
          <p className="hint danger">Run crashed before producing results.</p>
          <pre className="test-run-output">{runResult.output}</pre>
        </div>
      )}
    </section>
  )
}

export default RegressionPage
