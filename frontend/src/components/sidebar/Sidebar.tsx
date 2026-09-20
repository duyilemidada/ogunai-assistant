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

  return (
    <aside className="w-64 shrink-0 bg-bg-surface border-r border-border flex flex-col h-screen">
      <div className="px-4 py-4 border-b border-border">
        <h1 className="text-lg font-bold text-text-primary tracking-tight">
          Ogun AI
        </h1>
      </div>

      <div className="px-3 py-3">
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
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-text-muted truncate">
            {user?.email}
          </span>
          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={toggleTheme}
              className="text-text-muted hover:text-text-primary transition-colors"
              aria-label="Toggle theme"
              title={
                theme === 'dark'
                  ? 'Switch to light theme'
                  : 'Switch to dark theme'
              }
            >
              {theme === 'dark' ? '☀' : '☾'}
            </button>
            <button
              onClick={handleLogout}
              className="text-xs text-accent hover:underline"
            >
              Log out
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
