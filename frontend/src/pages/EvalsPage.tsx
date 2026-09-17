function EvalsPage() {
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
    </section>
  )
}

export default EvalsPage
