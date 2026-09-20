import Layout from '../components/Layout'
import MessageList from '../components/chat/MessageList'
import ChatInput from '../components/chat/ChatInput'
import { useStreamingChat } from '../hooks/useStreamingChat'
import { useChatStore } from '../stores/chatStore'
import { useResumeConversation } from '../hooks/useResumeConversation'

export default function ChatPage() {
  useResumeConversation() // hydrates messages when opening a conversation not yet in memory
  const { send, cancel, messages } = useStreamingChat()
  const isStreaming = useChatStore((s) => s.isStreaming)

  return (
    <Layout>
      <MessageList messages={messages} isSending={isStreaming} />
      <ChatInput onSend={send} onCancel={cancel} disabled={isStreaming} />
    </Layout>
  )
}
