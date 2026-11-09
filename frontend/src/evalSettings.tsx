import { useState, type ReactNode } from 'react'
import { EvalSettingsContext } from './useEvalSettings'

export function EvalSettingsProvider({ children }: { children: ReactNode }) {
  const [skipEvalServiceWorker, setSkipEvalServiceWorker] = useState(false)
  const [minScore, setMinScore] = useState<number | null>(null)
  const [requiredScorers, setRequiredScorers] = useState<string[] | null>(null)
  const [sampleRate, setSampleRate] = useState<number | null>(null)
  const [forceReviewEveryN, setForceReviewEveryN] = useState<number | null>(null)

  return (
    <EvalSettingsContext.Provider
      value={{
        skipEvalServiceWorker,
        setSkipEvalServiceWorker,
        minScore,
        setMinScore,
        requiredScorers,
        setRequiredScorers,
        sampleRate,
        setSampleRate,
        forceReviewEveryN,
        setForceReviewEveryN,
      }}
    >
      {children}
    </EvalSettingsContext.Provider>
  )
}
