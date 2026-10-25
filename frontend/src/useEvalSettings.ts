import { createContext, useContext } from 'react'

export interface EvalSettings {
  skipEvalServiceWorker: boolean
  setSkipEvalServiceWorker: (value: boolean) => void
}

export const EvalSettingsContext = createContext<EvalSettings | null>(null)

export function useEvalSettings(): EvalSettings {
  const context = useContext(EvalSettingsContext)
  if (!context) {
    throw new Error('useEvalSettings must be used within an EvalSettingsProvider')
  }
  return context
}
