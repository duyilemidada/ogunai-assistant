import { useNavigate } from 'react-router-dom'
import {
  useConversations,
  useDeleteConversation,
} from '../../hooks/useConversations'
import { useChatStore } from '../../stores/chatStore'
import ConversationItem from './ConversationItem'

type Convo = { id: number; title: string; updated_at?: string }

// The API sends naive UTC timestamps (no "Z"), so add one before parsing.
function parseDate(s?: string): Date | null {
  if (!s) return null
  const d = new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(s) ? s : s + 'Z')
  return isNaN(d.getTime()) ? null : d
}

function groupLabel(d: Date | null): string {
  if (!d) return 'Recent'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.round((today.getTime() - day.getTime()) / 86400000)
  if (diff <= 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  if (diff < 8) return 'Previous 7 days'
  return 'Older'
}

export default function ConversationList() {
  const { data, isLoading } = useConversations()
  const { mutate: remove } = useDeleteConversation()
  const activeId = useChatStore((s) => s.activeConversationId)
  const selectConversation = useChatStore((s) => s.selectConversation)
  const startNewChat = useChatStore((s) => s.startNewChat)
  const navigate = useNavigate()

  if (isLoading) {
    return (
      <div className="space-y-2 px-1 pt-2">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-8 animate-pulse rounded-lg bg-bg-elevated"
          />
        ))}
      </div>
    )
  }
  const conversations = (data ?? []) as unknown as Convo[]
  if (conversations.length === 0) {
    return (
      <p className="px-3 py-3 text-xs text-text-dim">
        No conversations yet. Start one above.
      </p>
    )
  }

  const handleDelete = (id: number) => {
    remove(id)
    if (id === activeId) startNewChat()
  }

  const groups = new Map<string, Convo[]>()
  for (const c of conversations) {
    const label = groupLabel(parseDate(c.updated_at))
    groups.set(label, [...(groups.get(label) ?? []), c])
  }

  return (
    <div className="pb-2">
      {[...groups.entries()].map(([label, items]) => (
        <div key={label}>
          <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-text-dim">
            {label}
          </p>
          <div className="flex flex-col gap-0.5">
            {items.map((c) => (
              <ConversationItem
                key={c.id}
                title={c.title}
                active={c.id === activeId}
                onClick={() => {
                  selectConversation(c.id)
                  navigate('/chat')
                }}
                onDelete={() => handleDelete(c.id)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
