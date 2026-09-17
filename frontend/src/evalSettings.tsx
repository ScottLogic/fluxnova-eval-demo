import { useState, type ReactNode } from 'react'
import { EvalSettingsContext } from './useEvalSettings'

export function EvalSettingsProvider({ children }: { children: ReactNode }) {
  const [skipEvalServiceWorker, setSkipEvalServiceWorker] = useState(false)
  const [autoEvalEnabled, setAutoEvalEnabled] = useState(true)

  return (
    <EvalSettingsContext.Provider
      value={{ skipEvalServiceWorker, setSkipEvalServiceWorker, autoEvalEnabled, setAutoEvalEnabled }}
    >
      {children}
    </EvalSettingsContext.Provider>
  )
}
