import { useState, useRef } from 'react'
import type { KeyboardEvent, ChangeEvent } from 'react'
import FileUploadButton from './FileUploadButton'
import AttachedDocumentChip from './AttachedDocumentChip'

interface Attachment {
  documentId: number
  filename: string
}

interface ChatInputProps {
  onSend: (message: string) => void
  onCancel?: () => void
  disabled: boolean
}

export default function ChatInput({
  onSend,
  onCancel,
  disabled,
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return

    // Prepend attachment references so the Supervisor/ResearchAgent can find
    // the document by ID — matches the "document N" phrasing ask_document expects.
    const attachmentPrefix = attachments
      .map((a) => `[Attached: document ${a.documentId} — ${a.filename}]`)
      .join('\n')
    const finalMessage = attachmentPrefix
      ? `${attachmentPrefix}\n${trimmed}`
      : trimmed

    onSend(finalMessage)
    setValue('')
    setAttachments([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 160) + 'px'
    }
  }

  return (
    <div className="border-t border-border bg-bg-base px-4 py-3">
      <div className="max-w-3xl mx-auto">
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((a) => (
              <AttachedDocumentChip
                key={a.documentId}
                documentId={a.documentId}
                filename={a.filename}
                onRemove={() =>
                  setAttachments((prev) =>
                    prev.filter((x) => x.documentId !== a.documentId),
                  )
                }
              />
            ))}
          </div>
        )}

        <div className="flex items-end gap-1 bg-bg-surface border border-border rounded-xl px-2 py-2 focus-within:border-accent transition-colors">
          <FileUploadButton
            onUploaded={(documentId, filename) =>
              setAttachments((prev) => [...prev, { documentId, filename }])
            }
          />
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
            placeholder="Message Ogun AI..."
            className="flex-1 bg-transparent resize-none outline-none text-text-primary text-[15px]
                       placeholder:text-text-dim py-1.5 max-h-40 disabled:opacity-50"
          />
          <button
            onClick={disabled ? onCancel : handleSend}
            disabled={disabled ? !onCancel : !value.trim()}
            className="shrink-0 w-8 h-8 rounded-lg bg-primary disabled:bg-bg-elevated
                       disabled:text-text-dim text-white flex items-center justify-center transition-colors"
            aria-label={disabled ? 'Stop' : 'Send message'}
          >
            {disabled ? (
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <rect x="4" y="4" width="16" height="16" rx="2" />
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
                  d="M22 2 11 13"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M22 2 15 22 11 13 2 9 22 2Z"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
        </div>
        <p className="text-center text-text-dim text-[11px] mt-2">
          Ogun AI can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  )
}
