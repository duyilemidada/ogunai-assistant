import { useEffect } from 'react'
import { useChatStore } from '../stores/chatStore'
import { fetchConversationMessages } from '../api/conversations'

/**
 * Fetches a conversation's message history from the backend the first time
 * it's opened in this browser session. After that, the in-memory copy in
 * chatStore is reused — no refetch until a full page reload clears state.
 */
export function useResumeConversation() {
  const activeConversationId = useChatStore((s) => s.activeConversationId)
  const isHydrated = useChatStore((s) => s.isHydrated)
  const hydrateConversation = useChatStore((s) => s.hydrateConversation)

  useEffect(() => {
    if (activeConversationId === null) return
    if (isHydrated(activeConversationId)) return

    let cancelled = false
    fetchConversationMessages(activeConversationId).then((messages) => {
      if (!cancelled) hydrateConversation(activeConversationId, messages)
    })
    return () => {
      cancelled = true
    }
  }, [activeConversationId])
}
