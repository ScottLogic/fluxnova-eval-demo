import { useNavigationStore } from '../store/navigationStore'
import { TABS } from '../tabs'

function TabContents() {
  const setActiveTab = useNavigationStore((state) => state.setActiveTab)

  return (
    <ul className="contents-list">
      {TABS.filter((tab) => tab.id !== 'landing').map((tab) => (
        <li key={tab.id}>
          <button type="button" className="contents-item" onClick={() => setActiveTab(tab.id)}>
            <span className="contents-item-label">{tab.label}</span>
            <span className="contents-item-description">{tab.description}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

export default TabContents
