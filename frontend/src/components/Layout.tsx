import type { ReactNode } from 'react'
import Sidebar from './sidebar/Sidebar'
import ActivityPanel from './activity/ActivityPanel'
import MobileTopBar from './MobileTopBar'
import { useUiStore } from '../stores/uiStore'

export default function Layout({ children }: { children: ReactNode }) {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)

  return (
    <div className="flex h-screen bg-bg-base overflow-hidden relative">
      {/* Mobile backdrop — tapping it closes the drawer */}
      {sidebarOpen && (
        <div
          onClick={toggleSidebar}
          className="fixed inset-0 bg-black/60 z-20 md:hidden"
        />
      )}

      {/* On mobile: fixed off-canvas drawer, toggled by translate-x.
          On desktop (md+): md:static + md:translate-x-0 forces it always visible,
          regardless of sidebarOpen state. */}
      <div
        className={`fixed md:static z-30 h-full transition-transform duration-200
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}
      >
        <Sidebar />
      </div>

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <MobileTopBar />
        <main className="flex-1 flex flex-col overflow-hidden">{children}</main>
      </div>

      <ActivityPanel />
    </div>
  )
}
