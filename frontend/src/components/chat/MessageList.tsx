import { useEffect, useRef } from 'react'
import type { Message } from '../../api/types'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'

const SUGGESTIONS = [
  {
    tag: 'Research',
    prompt: 'What changed recently in Nigerian fintech regulation?',
  },
  { tag: 'Code', prompt: 'Review my FastAPI auth code for security issues' },
  { tag: 'Fitness', prompt: 'Log my workout and check my injury risk' },
  { tag: 'Learning', prompt: 'Teach me SQL injection from first principles' },
]

export default function MessageList({
  messages,
  isSending,
  onQuickReply,
}: {
  messages: Message[]
  isSending: boolean
  onQuickReply?: (text: string) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, isSending])

  if (messages.length === 0 && !isSending) {
    return (
      <div className="flex flex-1 items-center justify-center overflow-y-auto px-4">
        <div className="anim-fade-up w-full max-w-2xl py-10 text-center">
          <div className="brand-gradient mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl shadow-pop">
            <span className="text-2xl font-bold text-on-primary">O</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight text-text-primary">
            How can I help today?
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-muted">
            Research, code, fitness and learning, with agents that show their
            work.
          </p>
          {onQuickReply && (
            <div className="mt-8 grid gap-3 text-left sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.tag}
                  onClick={() => onQuickReply(s.prompt)}
                  className="group rounded-xl border border-border bg-bg-surface p-4 shadow-soft transition hover:-translate-y-0.5 hover:border-primary/50"
                >
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-primary">
                    {s.tag}
                  </span>
                  <span className="mt-1 block text-sm text-text-primary">
                    {s.prompt}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl py-4">
        {messages.map((m, i) => (
          <MessageBubble
            key={m.id ?? i}
            message={m}
            canReply={!isSending && i === messages.length - 1}
            onQuickReply={onQuickReply}
          />
        ))}
        {isSending && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
