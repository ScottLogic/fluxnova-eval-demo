import type { Golden, RegressionGoldenProgress } from '../api'

interface GoldenRunProgressProps {
  goldens: Golden[]
  progress: RegressionGoldenProgress[]
}

function scenarioName(golden: Golden, index: number): string {
  return (golden.additional_metadata?.scenario as string) ?? `Scenario ${index + 1}`
}

function GoldenRunProgress({ goldens, progress }: GoldenRunProgressProps) {
  if (goldens.length === 0) {
    return null
  }

  const statusByName = new Map(progress.map((entry) => [entry.name, entry.status]))

  return (
    <div className="golden-progress">
      <p className="hint">Driving the live agent once per golden before the tests can run…</p>
      <ul className="golden-progress-list">
        {goldens.map((golden, index) => {
          const name = scenarioName(golden, index)
          const status = statusByName.get(name)
          return (
            <li key={name} className="golden-progress-item">
              {status === 'done' ? (
                <span className="golden-progress-icon golden-progress-done" aria-hidden="true">
                  ✓
                </span>
              ) : status === 'running' ? (
                <span className="spinner" aria-hidden="true" />
              ) : (
                <span className="golden-progress-icon golden-progress-pending" aria-hidden="true">
                  ·
                </span>
              )}
              <span className="golden-progress-name">{name}</span>
              <span className="golden-progress-state">
                {status === 'done' ? 'Done' : status === 'running' ? 'Running…' : 'Pending'}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default GoldenRunProgress
