import { create } from 'zustand'

type Theme = 'dark' | 'light'

interface UIState {
  sidebarOpen: boolean
  activityPanelOpen: boolean
  theme: Theme
  toggleSidebar: () => void
  openActivity: () => void
  closeActivity: () => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

// Read the saved theme, or fall back to the OS preference, defaulting to
// dark if neither is available. This runs once at module load — before
// React renders anything — so the correct theme applies from the very
// first paint. Doing this inside a useEffect instead would cause a visible
// flash of the wrong theme, since effects run after the DOM is painted.
function getInitialTheme(): Theme {
  const saved = localStorage.getItem('ogun-theme')
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark'
}

const initialTheme = getInitialTheme()
// Apply immediately at module load, synchronously, before the store or any
// component exists. This is the line that actually prevents the FOUC —
// everything else here just keeps state and DOM in sync afterward.
document.documentElement.setAttribute('data-theme', initialTheme)

export const useUiStore = create<UIState>((set, get) => ({
  // false by default: on mobile this is the drawer, and a drawer that's
  // open (with its dark backdrop) the instant the page loads is a bug,
  // not a feature. Desktop ignores this value entirely — Layout.tsx forces
  // the sidebar visible on md+ screens regardless of this flag.
  sidebarOpen: false,
  activityPanelOpen: false,
  theme: initialTheme,

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  openActivity: () => set({ activityPanelOpen: true }),
  closeActivity: () => set({ activityPanelOpen: false }),

  setTheme: (theme) => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('ogun-theme', theme)
    set({ theme })
  },

  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    get().setTheme(next)
  },
}))
