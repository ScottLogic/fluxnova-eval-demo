import type { RegressionScorerResult } from '../api'

interface ScorerResultsProps {
  scorers: RegressionScorerResult[]
}

function formatValue(value: RegressionScorerResult['value']): string {
  if (value == null) {
    return '—'
  }
  return typeof value === 'number' ? value.toFixed(2) : String(value)
}

function ScorerResults({ scorers }: ScorerResultsProps) {
  const failed = scorers.filter((scorer) => scorer.status === 'failed').length
  const applicable = scorers.filter((scorer) => scorer.status !== 'n/a').length

  return (
    <details className="scorer-results" open={failed > 0}>
      <summary>
        {applicable - failed}/{applicable} scorers passed
        {failed > 0 && <span className="scorer-results-failed"> · {failed} failed</span>}
      </summary>
      <table className="scorer-results-table">
        <tbody>
          {scorers.map((scorer) => (
            <tr key={scorer.name}>
              <td className="scorer-results-name">{scorer.name}</td>
              <td>
                <span className={`status-badge status-${scorer.status === 'n/a' ? 'na' : scorer.status}`}>
                  {scorer.status}
                </span>
              </td>
              <td className="scorer-results-value">{formatValue(scorer.value)}</td>
              <td className="scorer-results-rationale">{scorer.status === 'n/a' ? '' : scorer.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

export default ScorerResults
