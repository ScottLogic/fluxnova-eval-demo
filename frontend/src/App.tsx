import './App.css'
import { EvalSettingsProvider } from './evalSettings'
import { useNavigationStore } from './store/navigationStore'
import { TABS } from './tabs'

function App() {
  const activeTab = useNavigationStore((state) => state.activeTab)
  const setActiveTab = useNavigationStore((state) => state.setActiveTab)
  const ActivePage = TABS.find((tab) => tab.id === activeTab)?.Component ?? TABS[0].Component

  return (
    <EvalSettingsProvider>
      <div className="app-shell">
        <div className="mesh" aria-hidden="true" />
        <header className="topbar">
          <button type="button" className="brand" onClick={() => setActiveTab('landing')}>
            <img className="brand-logo" src="/logos/finos.png" alt="FINOS" />
            <span className="brand-title">Fluxnova Eval Demo</span>
          </button>
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
