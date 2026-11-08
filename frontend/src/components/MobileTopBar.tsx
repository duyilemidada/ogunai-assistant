import { useUiStore } from '../stores/uiStore'

export default function MobileTopBar() {
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  return (
    <div className="glass sticky top-0 z-10 flex items-center gap-3 border-b border-border px-4 py-3 md:hidden">
      <button
        onClick={toggleSidebar}
        aria-label="Open menu"
        className="-ml-1 rounded-md p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
      >
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
      <div className="brand-gradient flex h-6 w-6 items-center justify-center rounded-md">
        <span className="text-[11px] font-bold text-on-primary">O</span>
      </div>
      <span className="text-sm font-semibold text-text-primary">Ogun AI</span>
    </div>
  )
}
