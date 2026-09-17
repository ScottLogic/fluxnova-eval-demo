async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

async function post<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: 'POST' })
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export interface RegressionTests {
  tests: string[]
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

export function startRegressionRun(): Promise<RegressionRunStarted> {
  return post('/api/regression/runs')
}

export function fetchRegressionRun(runId: string): Promise<RegressionRunResult> {
  return get(`/api/regression/runs/${runId}`)
}
