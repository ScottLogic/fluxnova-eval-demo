import { useState } from 'react'
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
    <div id="app">
      <header id="app-header">
        <h1>Fluxnova Eval Demo</h1>
        <nav id="tab-nav">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={tab.id === activeTab ? 'tab active' : 'tab'}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>
      <main id="app-content">
        <ActivePage />
      </main>
    </div>
  )
}

export default App
