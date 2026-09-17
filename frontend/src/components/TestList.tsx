import type { RegressionRunResult, RegressionTestResult } from '../api'

interface TestListProps {
  tests: string[] | null
  runResult: RegressionRunResult | null
}

function shortTestName(nodeId: string): string {
  const index = nodeId.indexOf('::')
  return index === -1 ? nodeId : nodeId.slice(index + 2).replace("_", " ");
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
    <ul className="test-list">
      {tests.map((nodeId) => {
        const result = outcomeByNodeId.get(nodeId)
        return (
          <li key={nodeId} className="test-list-item">
            <span className="test-list-name">{shortTestName(nodeId)}</span>
            <span className="test-list-meta">
              {result && (
                <span className={`status-badge status-${result.outcome}`}>{result.outcome}</span>
              )}
              {result && (
                <span className="test-list-duration">{formatDuration(result.durationSeconds)}</span>
              )}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export default TestList
