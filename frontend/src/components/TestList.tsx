import type { RegressionRunResult, RegressionTest, RegressionTestResult } from '../api'

interface TestListProps {
  tests: RegressionTest[] | null
  runResult: RegressionRunResult | null
}

function shortTestName(nodeId: string): string {
  const index = nodeId.indexOf('::')
  return index === -1 ? nodeId : nodeId.slice(index + 2).replaceAll("_", " ");
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
      {tests.map(({ name, description }) => {
        const result = outcomeByNodeId.get(name)
        return (
          <li key={name} className="test-list-item" title={description || undefined}>
            <span className="test-list-name">{shortTestName(name)}</span>
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
