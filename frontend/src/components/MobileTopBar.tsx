import { useUiStore } from '../stores/uiStore'

export default function MobileTopBar() {
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  return (
    <div className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-border bg-bg-base">
      <button onClick={toggleSidebar} aria-label="Open menu">
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
        </svg>
      </button>
      <span className="text-sm font-semibold text-text-primary">Ogun AI</span>
    </div>
  )
}
