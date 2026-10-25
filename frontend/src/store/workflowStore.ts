import { create } from 'zustand'
import {
  fetchWorkflowConfig,
  fetchWorkflowRun,
  startWorkflowRun,
  type AgentConfig,
  type WorkflowRunStatus,
  type WorkflowVariables,
} from '../api'

const POLL_MS = 2000

interface WorkflowState {
  defaults: WorkflowVariables | null
  agentConfig: AgentConfig | null
  configError: string | null
  configLoaded: boolean

  instanceId: string | null
  run: WorkflowRunStatus | null
  runError: string | null
  submitting: boolean

  loadConfig: () => void
  startRun: (values: WorkflowVariables) => void
}

// Module-scoped so an in-flight poll survives the WorkflowPage component
// unmounting when the user switches tabs — see regressionStore's identical
// pattern for the reasoning.
let pollTimer: number | undefined

function stopPolling() {
  window.clearTimeout(pollTimer)
}

function pollRun(instanceId: string, set: (partial: Partial<WorkflowState>) => void) {
  stopPolling()

  function tick() {
    fetchWorkflowRun(instanceId)
      .then((result) => {
        set({ run: result, runError: null })
        if (result.status === 'active') {
          pollTimer = window.setTimeout(tick, POLL_MS)
        }
      })
      .catch((error: unknown) => {
        set({ runError: error instanceof Error ? error.message : 'Failed to fetch run status' })
      })
  }

  tick()
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  defaults: null,
  agentConfig: null,
  configError: null,
  configLoaded: false,

  instanceId: null,
  run: null,
  runError: null,
  submitting: false,

  loadConfig: () => {
    if (get().configLoaded) {
      return
    }
    fetchWorkflowConfig()
      .then((config) =>
        set({
          defaults: config.variables,
          agentConfig: config.agentConfig,
          configError: null,
          configLoaded: true,
        }),
      )
      .catch((error: unknown) => {
        set({ configError: error instanceof Error ? error.message : 'Failed to load defaults' })
      })
  },

  startRun: (values) => {
    set({ submitting: true, runError: null, run: null })
    startWorkflowRun(values)
      .then((payload) => {
        set({ instanceId: payload.instanceId })
        pollRun(payload.instanceId, set)
      })
      .catch((error: unknown) => {
        set({ runError: error instanceof Error ? error.message : 'Failed to start run' })
      })
      .finally(() => set({ submitting: false }))
  },
}))
