import type { Message } from '../../api/types'
import MarkdownRenderer from './MarkdownRenderer'

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-2">
        <div className="max-w-[70%] bg-bg-elevated rounded-2xl rounded-br-sm px-4 py-2.5">
          <p className="text-text-primary text-[15px] whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center">
          <span className="text-[10px] font-bold text-white">O</span>
        </div>
        <span className="text-xs text-text-muted font-medium">Ogun AI</span>
      </div>
      <div className="pl-7 text-text-primary">
        <MarkdownRenderer content={message.content} />
      </div>
    </div>
  )
}
