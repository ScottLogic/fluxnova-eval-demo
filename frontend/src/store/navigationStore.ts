import { create } from 'zustand'
import type { TabId } from '../tabs'

interface NavigationState {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void
}

// Lifted out of App.tsx (rather than local useState) so other components —
// e.g. LandingPage's "Contents" list — can navigate to a tab without prop
// drilling, matching the zustand pattern already used for
// regressionStore/workflowStore.
export const useNavigationStore = create<NavigationState>((set) => ({
  activeTab: 'landing',
  setActiveTab: (tab) => set({ activeTab: tab }),
}))
