import { useEffect, useRef } from 'react'
import type { Message } from '../../api/types'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'

export default function MessageList({
  messages,
  isSending,
}: {
  messages: Message[]
  isSending: boolean
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, isSending])

  if (messages.length === 0 && !isSending) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-text-primary mb-1">
            Ogun AI
          </h2>
          <p className="text-text-muted text-sm">
            Ask anything — research, code, fitness, learning.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto py-4">
        {messages.map((m, i) => (
          <MessageBubble key={m.id ?? i} message={m} />
        ))}
        {isSending && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
