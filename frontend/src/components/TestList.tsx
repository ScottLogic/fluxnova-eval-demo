import type { RegressionRunResult, RegressionTest, RegressionTestResult } from '../api'
import ScorerResults from './ScorerResults'

interface TestListProps {
  tests: RegressionTest[] | null
  runResult: RegressionRunResult | null
}

function shortTestName(nodeId: string): string {
  // Parametrized tests (one per golden) are named by their parameter id, i.e. the golden's scenario.
  const param = nodeId.match(/\[(.+)\]$/)
  if (param) {
    return param[1]
  }
  const index = nodeId.indexOf('::')
  return index === -1 ? nodeId : nodeId.slice(index + 2).replaceAll('_', ' ')
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) {
    return '—'
  }
  return `${seconds.toFixed(2)}s`
}

function TestList({ tests, runResult }: TestListProps) {
  if (!tests) {
    return null
  }

  const outcomeByNodeId = new Map<string, RegressionTestResult>(
    (runResult?.tests ?? []).map((test) => [test.nodeId, test]),
  )

  return (
    <table className="test-table">
      <thead>
        <tr>
          <th>Golden</th>
          <th>Status</th>
          <th>Duration</th>
        </tr>
      </thead>
      <tbody>
        {tests.map(({ name, description }) => {
          const result = outcomeByNodeId.get(name)
          return (
            <tr key={name} className="test-table-row">
              <td>
                <span className="test-table-name">{shortTestName(name)}</span>
                {description && <p className="test-table-description">{description}</p>}
                {result?.scorers && <ScorerResults scorers={result.scorers} />}
              </td>
              <td>
                {result?.outcome === 'running' ? (
                  <span className="spinner" aria-hidden="true" />
                ) : result ? (
                  <span className={`status-badge status-${result.outcome}`}>{result.outcome}</span>
                ) : (
                  '—'
                )}
              </td>
              <td className="test-table-duration">{result ? formatDuration(result.durationSeconds) : '—'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default TestList
