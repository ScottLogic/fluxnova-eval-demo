import { useEffect, useState } from 'react'
import { fetchAutoEvalConfig, updateAutoEvalConfig } from '../api'
import Toggle from './Toggle'

function AutoEvalToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAutoEvalConfig()
      .then((config) => {
        setEnabled(config.enabled)
        setError(null)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load auto-eval status')
      })
  }, [])

  function handleChange(checked: boolean) {
    setPending(true)
    setError(null)
    updateAutoEvalConfig(checked)
      .then((config) => setEnabled(config.enabled))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to update auto-eval')
      })
      .finally(() => setPending(false))
  }

  return (
    <div>
      <Toggle
        label="Auto-eval (trace listener)"
        title="Sets the trace listener's live sample rate: on scores every trace, off scores none. Takes effect immediately, independent of any single run."
        checked={enabled ?? false}
        disabled={enabled === null || pending}
        onChange={handleChange}
      />
      {error && <p className="hint danger">{error}</p>}
    </div>
  )
}

export default AutoEvalToggle
