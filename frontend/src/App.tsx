import { useState } from 'react'
import './App.css'
import { EvalSettingsProvider } from './evalSettings'
import LandingPage from './pages/LandingPage'
import EvalsPage from './pages/EvalsPage'
import RegressionPage from './pages/RegressionPage'
import TelemetryPage from './pages/TelemetryPage'
import WorkflowPage from './pages/WorkflowPage'
import LoanAssessmentPage from './pages/LoanAssessmentPage'
import ArchitecturePage from './pages/ArchitecturePage'

const TABS = [
  { id: 'landing', label: 'Home', Component: LandingPage },
  { id: 'loan-assessment', label: 'Loan assessment', Component: LoanAssessmentPage },
  { id: 'regression', label: 'Regression', Component: RegressionPage },
  { id: 'workflow', label: 'Workflow run', Component: WorkflowPage },
  { id: 'evals', label: 'Evals', Component: EvalsPage },
  { id: 'telemetry', label: 'Telemetry', Component: TelemetryPage },
  { id: 'architecture', label: 'Architecture', Component: ArchitecturePage },
] as const

type TabId = (typeof TABS)[number]['id']

function App() {
  const [activeTab, setActiveTab] = useState<TabId>('landing')
  const ActivePage = TABS.find((tab) => tab.id === activeTab)?.Component ?? LandingPage

  return (
    <EvalSettingsProvider>
      <div className="app-shell">
        <div className="mesh" aria-hidden="true" />
        <header className="topbar">
          <button
              type="button"
              className="brand"
              onClick={() => window.location.href="/"}
          >
            <img className="brand-logo" src="/logos/finos.png" alt="FINOS" />
            <span className="brand-title">
          </span>
          </button>
          <span className="brand">
            <span className="brand-title" title="home" onClick={() => window.location.href="/"}>Fluxnova Eval Demo</span>
          </span>
          <nav className="topbar-nav" aria-label="Primary">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`topbar-nav-link${tab.id === activeTab ? ' is-active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </header>
        <main className="stage">
          <div className="stage-inner">
            <ActivePage />
          </div>
        </main>
      </div>
    </EvalSettingsProvider>
  )
}

export default App
