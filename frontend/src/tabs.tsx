import type { ComponentType } from 'react'
import ArchitecturePage from './pages/ArchitecturePage'
import EvalsPage from './pages/EvalsPage'
import LandingPage from './pages/LandingPage'
import LoanAssessmentPage from './pages/LoanAssessmentPage'
import RegressionPage from './pages/RegressionPage'
import TelemetryPage from './pages/TelemetryPage'
import WorkflowPage from './pages/WorkflowPage'

export interface TabDefinition {
  id: string
  label: string
  description: string
  Component: ComponentType
}

// Single source of truth for the top nav (App.tsx) and the home page's
// "Contents" list (LandingPage.tsx), so a tab's label/description can't drift
// between the two.
export const TABS: TabDefinition[] = [
  {
    id: 'landing',
    label: 'Home',
    description: 'This page.',
    Component: LandingPage,
  },
  {
    id: 'loan-assessment',
    label: 'Loan assessment',
    description:
      'View the two BPMN processes behind the loan use case: the full loan approval process, and the AI credit-risk agent subprocess exercised by the regression suite.',
    Component: LoanAssessmentPage,
  },
  {
    id: 'regression',
    label: 'Regression',
    description:
      'View available regression tests, trigger a run against the live agent, and see per-test pass/fail results as they happen.',
    Component: RegressionPage,
  },
  {
    id: 'workflow',
    label: 'Workflow run',
    description:
      'Trigger a run of the loan approval BPMN with editable input, and toggle evals independently for that run.',
    Component: WorkflowPage,
  },
  {
    id: 'evals',
    label: 'Evals',
    description:
      'See which evals are configured for the auto-eval (trace listener) and eval service worker paths.',
    Component: EvalsPage,
  },
  {
    id: 'telemetry',
    label: 'Telemetry',
    description:
      'See what gen_ai metrics and traces Fluxnova exports, with links out to Grafana and the MLflow dashboard.',
    Component: TelemetryPage,
  },
  {
    id: 'architecture',
    label: 'Architecture',
    description:
      "A diagram of how the project's components fit together — Fluxnova, MLflow, the OTel Collector, and the eval services.",
    Component: ArchitecturePage,
  },
] as const

export type TabId = (typeof TABS)[number]['id']
