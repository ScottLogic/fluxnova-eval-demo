import { useState } from 'react'
import './App.css'
import { EvalSettingsProvider } from './evalSettings'
import EvalsPage from './pages/EvalsPage'
import RegressionPage from './pages/RegressionPage'
import WorkflowPage from './pages/WorkflowPage'

const TABS = [
  { id: 'regression', label: 'Regression', Component: RegressionPage },
  { id: 'workflow', label: 'Workflow run', Component: WorkflowPage },
  { id: 'evals', label: 'Evals', Component: EvalsPage },
] as const

type TabId = (typeof TABS)[number]['id']

function App() {
  const [activeTab, setActiveTab] = useState<TabId>('regression')
  const ActivePage = TABS.find((tab) => tab.id === activeTab)?.Component ?? RegressionPage

  return (
    <EvalSettingsProvider>
      <div className="app-shell">
        <div className="mesh" aria-hidden="true" />
        <header className="topbar">
          <span className="brand">
            <span className="brand-title">Fluxnova Eval Demo</span>
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
          <ActivePage />
        </main>
      </div>
    </EvalSettingsProvider>
  )
}

export default App
