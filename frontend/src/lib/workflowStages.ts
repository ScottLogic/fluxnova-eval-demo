import type { WorkflowStage } from '../api'

interface FlatStage {
  path: string[]
  startTime: string | null
  endTime: string | null
}

function flattenStages(stages: WorkflowStage[], parentPath: string[] = []): FlatStage[] {
  return stages.flatMap((stage) => {
    const path = [...parentPath, stage.name]
    const self: FlatStage = { path, startTime: stage.startTime, endTime: stage.endTime }
    const children = stage.children ? flattenStages(stage.children, path) : []
    return [self, ...children]
  })
}

/**
 * The most relevant single stage to show right now: the most-recently-started
 * unfinished one (naturally descends into whichever child is actually active,
 * e.g. a tool call inside the agent step, rather than just naming the parent
 * for its whole duration), or — once nothing is left running — the
 * last-completed one for context.
 */
export function currentStagePath(stages: WorkflowStage[]): string[] | null {
  const flat = flattenStages(stages)

  const running = flat.filter((stage) => stage.startTime && !stage.endTime)
  if (running.length > 0) {
    running.sort((a, b) => (a.startTime! < b.startTime! ? 1 : -1))
    return running[0].path
  }

  const ended = flat.filter((stage) => stage.endTime)
  if (ended.length > 0) {
    ended.sort((a, b) => (a.endTime! < b.endTime! ? 1 : -1))
    return ended[0].path
  }

  return null
}
