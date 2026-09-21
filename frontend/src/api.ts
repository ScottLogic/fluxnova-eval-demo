async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export interface RegressionTest {
  name: string
  description: string
}

export interface RegressionTests {
  tests: RegressionTest[]
}

export interface Golden {
  input: string
  expected_output: string
  context: string[]
  additional_metadata: Record<string, unknown>
  input_variables: Record<string, unknown>
  tool_responses: Record<string, unknown>
}

export interface Goldens {
  goldens: Golden[]
}

export interface RegressionRunStarted {
  runId: string
}

export interface RegressionTestResult {
  nodeId: string
  outcome: string
  durationSeconds: number | null
}

export interface RegressionRunResult {
  runId: string
  status: 'running' | 'passed' | 'failed' | 'error'
  exitCode?: number
  summary?: Record<string, number>
  tests?: RegressionTestResult[]
  output?: string
}

export function fetchRegressionTests(): Promise<RegressionTests> {
  return get('/api/regression/tests')
}

export function fetchGoldens(): Promise<Goldens> {
  return get('/api/regression/goldens')
}

export function startRegressionRun(): Promise<RegressionRunStarted> {
  return post('/api/regression/runs')
}

export function fetchRegressionRun(runId: string): Promise<RegressionRunResult> {
  return get(`/api/regression/runs/${runId}`)
}

export type WorkflowVariables = Record<string, string | number | boolean>

export interface WorkflowConfig {
  processKey: string
  variables: WorkflowVariables
}

export interface WorkflowRunStarted {
  instanceId: string
}

export interface WorkflowRunStatus {
  instanceId: string
  status: 'active' | 'completed' | 'terminated' | 'error'
  state?: string
  variables?: WorkflowVariables
}

export function fetchWorkflowConfig(): Promise<WorkflowConfig> {
  return get('/api/workflow/config')
}

export function startWorkflowRun(variableOverrides: WorkflowVariables): Promise<WorkflowRunStarted> {
  return post('/api/workflow/runs', variableOverrides)
}

export function fetchWorkflowRun(instanceId: string): Promise<WorkflowRunStatus> {
  return get(`/api/workflow/runs/${instanceId}`)
}

export interface AutoEvalConfig {
  enabled: boolean
}

export function fetchAutoEvalConfig(): Promise<AutoEvalConfig> {
  return get('/api/evals/auto-eval')
}

export function updateAutoEvalConfig(enabled: boolean): Promise<AutoEvalConfig> {
  return post('/api/evals/auto-eval', { enabled })
}

export interface EvalScorer {
  name: string
  description: string
}

export interface EvalDefinitions {
  listener: EvalScorer[]
  serviceWorker: EvalScorer[]
}

export function fetchEvalDefinitions(): Promise<EvalDefinitions> {
  return get('/api/evals/definitions')
}
