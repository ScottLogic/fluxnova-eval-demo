import { useState, type ReactNode } from 'react'
import { EvalSettingsContext } from './useEvalSettings'

export function EvalSettingsProvider({ children }: { children: ReactNode }) {
  const [skipEvalServiceWorker, setSkipEvalServiceWorker] = useState(false)

  return (
    <EvalSettingsContext.Provider value={{ skipEvalServiceWorker, setSkipEvalServiceWorker }}>
      {children}
    </EvalSettingsContext.Provider>
  )
}
