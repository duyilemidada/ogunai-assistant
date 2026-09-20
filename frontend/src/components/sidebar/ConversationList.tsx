import { useNavigate } from 'react-router-dom'
import {
  useConversations,
  useDeleteConversation,
} from '../../hooks/useConversations'
import { useChatStore } from '../../stores/chatStore'
import ConversationItem from './ConversationItem'

export default function ConversationList() {
  const { data: conversations, isLoading } = useConversations()
  const { mutate: remove } = useDeleteConversation()
  const activeId = useChatStore((s) => s.activeConversationId)
  const selectConversation = useChatStore((s) => s.selectConversation)
  const startNewChat = useChatStore((s) => s.startNewChat)
  const navigate = useNavigate()

  if (isLoading)
    return <p className="text-text-dim text-xs px-3 py-2">Loading...</p>
  if (!conversations || conversations.length === 0) {
    return (
      <p className="text-text-dim text-xs px-3 py-2">No conversations yet</p>
    )
  }

  const handleDelete = (id: number) => {
    remove(id)
    if (id === activeId) startNewChat()
  }

  return (
    <div className="flex flex-col gap-0.5">
      {conversations.map((c) => (
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
  )
}
