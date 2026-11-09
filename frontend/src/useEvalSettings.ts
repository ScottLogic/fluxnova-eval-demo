import { createContext, useContext } from 'react'

export interface EvalSettings {
  skipEvalServiceWorker: boolean
  setSkipEvalServiceWorker: (value: boolean) => void
  // Per-run guardrail thresholds. null means "use the BPMN task's default".
  minScore: number | null
  setMinScore: (value: number | null) => void
  requiredScorers: string[] | null
  setRequiredScorers: (value: string[] | null) => void
}

export const EvalSettingsContext = createContext<EvalSettings | null>(null)

export function useEvalSettings(): EvalSettings {
  const context = useContext(EvalSettingsContext)
  if (!context) {
    throw new Error('useEvalSettings must be used within an EvalSettingsProvider')
  }
  return context
}
