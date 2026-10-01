import type { EvalScorer } from '../api'

interface ScorerTableProps {
  scorers: EvalScorer[]
}

function UsedMark({ used }: { used: boolean }) {
  return (
    <span className={used ? 'scorer-used' : 'scorer-unused'} aria-label={used ? 'Yes' : 'No'}>
      {used ? '✓' : '✕'}
    </span>
  )
}

function ScorerTable({ scorers }: ScorerTableProps) {
  if (scorers.length === 0) {
    return <p className="hint">No scorers configured.</p>
  }

  return (
    <div className="metrics-table-wrap">
      <table className="metrics-table scorer-table">
        <thead>
          <tr>
            <th>Scorer</th>
            <th>Type</th>
            <th>Description</th>
            <th>Auto-eval</th>
            <th>Eval service worker</th>
            <th>Regression</th>
          </tr>
        </thead>
        <tbody>
          {scorers.map((scorer) => (
            <tr key={scorer.name}>
              <td>{scorer.name}</td>
              <td>
                <span
                  className={`status-badge ${scorer.deterministic ? 'status-deterministic' : 'status-non-deterministic'}`}
                >
                  {scorer.deterministic ? 'deterministic' : 'LLM judge'}
                </span>
              </td>
              <td>{scorer.description || 'No description available.'}</td>
              <td className="centered">
                <UsedMark used={scorer.usedInAutoEval} />
              </td>
              <td className="centered">
                <UsedMark used={scorer.usedInEvalServiceWorker} />
              </td>
              <td className="centered">
                <UsedMark used={scorer.usedInRegression} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default ScorerTable
