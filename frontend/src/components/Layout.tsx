import type { ReactNode } from 'react'
import Sidebar from './sidebar/Sidebar'
import ActivityPanel from './activity/ActivityPanel'
import MobileTopBar from './MobileTopBar'
import { useUiStore } from '../stores/uiStore'

export default function Layout({ children }: { children: ReactNode }) {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)

  return (
    <div className="relative flex h-screen overflow-hidden bg-bg-base">
      {/* Mobile backdrop — tapping it closes the drawer */}
      {sidebarOpen && (
        <div
          onClick={toggleSidebar}
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm md:hidden"
        />
      )}

      {/* Mobile: off-canvas drawer. Desktop (md+): always visible. */}
      <div
        className={`fixed z-30 h-full transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0 shadow-pop' : '-translate-x-full'
        }`}
      >
        <Sidebar />
      </div>

      <div className="ambient-bg flex min-w-0 flex-1 flex-col overflow-hidden">
        <MobileTopBar />
        <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
      </div>

      <ActivityPanel />
    </div>
  )
}
