import { NavLink } from 'react-router-dom'

export default function NavRail() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
      isActive
        ? 'bg-bg-elevated text-text-primary'
        : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
    }`

  return (
    <nav className="flex flex-col gap-0.5 px-3 py-2 border-t border-border">
      <NavLink to="/chat" className={linkClass}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Chat
      </NavLink>
      <NavLink to="/memory" className={linkClass}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M12 2a4 4 0 0 0-4 4v1a3 3 0 0 0-2 2.83V12a3 3 0 0 0 1 2.24V16a4 4 0 0 0 4 4h2a4 4 0 0 0 4-4v-1.76A3 3 0 0 0 18 12v-2.17A3 3 0 0 0 16 7V6a4 4 0 0 0-4-4Z"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Memory
      </NavLink>
    </nav>
  )
}
