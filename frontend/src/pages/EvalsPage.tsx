import { useEffect, useState } from 'react'
import { fetchEvalDefinitions, type EvalDefinitions } from '../api'
import ScorerList from '../components/ScorerList'

function EvalsPage() {
  const [definitions, setDefinitions] = useState<EvalDefinitions | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchEvalDefinitions()
      .then((result) => {
        setDefinitions(result)
        setError(null)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load eval definitions')
      })
  }, [])

  return (
    <section className="panel">
      <div className="panel-head">
        <p className="eyebrow">Evals</p>
        <h1>Evals</h1>
        <p className="panel-copy">
          See which evals are configured for both auto-eval (listener) and the eval service
          worker, and review the metrics and traces Fluxnova exports. Toggle auto-eval and the
          eval service worker for the next run from the Workflow tab.
        </p>
      </div>

      {error && <p className="hint danger">{error}</p>}
      {!definitions && !error && <p className="hint">Loading eval definitions…</p>}

      {definitions && (
        <>
          <ScorerList title="Auto-eval (listener) scorers" scorers={definitions.listener} />
          <ScorerList title="Eval service worker scorers" scorers={definitions.serviceWorker} />
        </>
      )}
    </section>
  )
}

export default EvalsPage
