import { useNavigate } from 'react-router-dom'
import { useChatStore } from '../../stores/chatStore'
import { useAuthStore } from '../../stores/authStore'
import { useUiStore } from '../../stores/uiStore'
import NewChatButton from './NewChatButton'
import ConversationList from './ConversationList'
import NavRail from './NavRail'

export default function Sidebar() {
  const startNewChat = useChatStore((s) => s.startNewChat)
  const { user, logout } = useAuthStore()
  const { theme, toggleTheme } = useUiStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }
  const initial = (user?.email ?? '?').charAt(0).toUpperCase()

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col border-r border-border bg-bg-surface">
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="brand-gradient flex h-8 w-8 items-center justify-center rounded-lg shadow-soft">
          <span className="text-sm font-bold text-on-primary">O</span>
        </div>
        <h1 className="text-[17px] font-semibold tracking-tight text-text-primary">
          Ogun AI
        </h1>
      </div>

      <div className="px-3 pb-2">
        <NewChatButton
          onClick={() => {
            startNewChat()
            navigate('/chat')
          }}
        />
      </div>

      <div className="flex-1 overflow-y-auto px-3">
        <ConversationList />
      </div>

      <NavRail />

      <div className="border-t border-border px-3 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-bg-elevated text-xs font-semibold text-text-primary">
            {initial}
          </div>
          <span
            className="min-w-0 flex-1 truncate text-xs text-text-muted"
            title={user?.email}
          >
            {user?.email}
          </span>
          <button
            onClick={toggleTheme}
            className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
            aria-label="Toggle theme"
            title={
              theme === 'dark'
                ? 'Switch to light theme'
                : 'Switch to dark theme'
            }
          >
            {theme === 'dark' ? (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="4" />
                <path
                  d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path
                  d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
          <button
            onClick={handleLogout}
            className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-error"
            aria-label="Log out"
            title="Log out"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path
                d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>
    </aside>
  )
}
