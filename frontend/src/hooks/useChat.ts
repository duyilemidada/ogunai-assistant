import { useChatStore } from '../stores/chatStore'
import { sendMessage } from '../api/chat'

export function useChat() {
  const {
    activeConversationId,
    addUserMessage,
    resolveConversation,
    addAgentMessage,
    setSending,
    currentMessages,
  } = useChatStore()

  const send = async (text: string) => {
    const wasNewConversation = activeConversationId === null
    const conversationIdAtSendTime = activeConversationId

    addUserMessage(text)
    setSending(true)

    try {
      const response = await sendMessage({
        message: text,
        conversation_id: conversationIdAtSendTime,
      })

      if (wasNewConversation) {
        // First message in a new chat — register it in the sidebar with the
        // message text as a title, same behaviour as the backend's own default.
        resolveConversation(response.conversation_id, text.slice(0, 50))
        addAgentMessage(response.conversation_id, response)
      } else if (conversationIdAtSendTime) {
        addAgentMessage(conversationIdAtSendTime, response)
      }
    } catch (err: any) {
      const errorText =
        err?.response?.data?.error?.message ||
        err?.response?.data?.error?.details?.[0]?.msg ||
        'Something went wrong. Please try again.'

      const targetId = wasNewConversation ? null : conversationIdAtSendTime
      if (targetId) {
        addAgentMessage(targetId, {
          role: 'supervisor',
          content: `⚠️ ${errorText}`,
        })
      }
      // If it failed on a brand-new chat, there's no conversation to attach
      // the error to yet — it just won't show. Acceptable for Phase 2;
      // Phase 3's activity panel will surface this properly.
    } finally {
      setSending(false)
    }
  }

  return { send, messages: currentMessages() }
}
