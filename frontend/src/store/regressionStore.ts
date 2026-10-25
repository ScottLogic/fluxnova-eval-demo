import { create } from 'zustand'
import {
  fetchGoldens,
  fetchRegressionRun,
  fetchRegressionTests,
  startRegressionRun,
  type Golden,
  type RegressionRunResult,
  type RegressionTest,
} from '../api'

const POLL_MS = 2000

interface RegressionState {
  tests: RegressionTest[] | null
  testsError: string | null
  testsLoaded: boolean

  goldens: Golden[]
  goldensError: string | null
  goldensLoaded: boolean

  runId: string | null
  runResult: RegressionRunResult | null
  runError: string | null
  starting: boolean

  loadTests: () => void
  loadGoldens: () => void
  startRun: () => void
}

// Module-scoped (not React state) so an in-flight poll survives the
// RegressionPage component unmounting when the user switches tabs — the
// store keeps polling in the background and the page just re-reads
// whatever `runResult` is current when it remounts.
let pollTimer: number | undefined

function stopPolling() {
  window.clearTimeout(pollTimer)
}

function pollRun(runId: string, set: (partial: Partial<RegressionState>) => void) {
  stopPolling()

  function tick() {
    fetchRegressionRun(runId)
      .then((result) => {
        set({ runResult: result, runError: null })
        if (result.status === 'running') {
          pollTimer = window.setTimeout(tick, POLL_MS)
        }
      })
      .catch((error: unknown) => {
        set({ runError: error instanceof Error ? error.message : 'Failed to fetch run status' })
      })
  }

  tick()
}

export const useRegressionStore = create<RegressionState>((set, get) => ({
  tests: null,
  testsError: null,
  testsLoaded: false,

  goldens: [],
  goldensError: null,
  goldensLoaded: false,

  runId: null,
  runResult: null,
  runError: null,
  starting: false,

  loadTests: () => {
    if (get().testsLoaded) {
      return
    }
    fetchRegressionTests()
      .then((payload) => set({ tests: payload.tests, testsError: null, testsLoaded: true }))
      .catch((error: unknown) => {
        set({ testsError: error instanceof Error ? error.message : 'Failed to load tests' })
      })
  },

  loadGoldens: () => {
    if (get().goldensLoaded) {
      return
    }
    fetchGoldens()
      .then((payload) => set({ goldens: payload.goldens, goldensError: null, goldensLoaded: true }))
      .catch((error: unknown) => {
        set({ goldensError: error instanceof Error ? error.message : 'Failed to load tests' })
      })
  },

  startRun: () => {
    set({ starting: true, runError: null, runResult: null })
    startRegressionRun()
      .then((payload) => {
        set({ runId: payload.runId })
        pollRun(payload.runId, set)
      })
      .catch((error: unknown) => {
        set({ runError: error instanceof Error ? error.message : 'Failed to start run' })
      })
      .finally(() => set({ starting: false }))
  },
}))
