import { useState, useRef, useEffect } from 'react'
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
  const [stopping, setStopping] = useState(false)
  useEffect(() => {
    if (!disabled) setStopping(false)
  }, [disabled])
  const handleStop = () => {
    if (stopping) return
    setStopping(true)
    onCancel?.()
  }
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canSend = value.trim().length > 0

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
      el.style.height = Math.min(el.scrollHeight, 180) + 'px'
    }
  }

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto max-w-3xl">
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
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

        <div className="flex items-end gap-1.5 rounded-2xl border border-border bg-bg-surface px-2.5 py-2 shadow-soft transition focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-primary/10">
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
            className="max-h-44 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-relaxed text-text-primary outline-none placeholder:text-text-dim disabled:opacity-50"
          />
          <button
            onClick={disabled ? handleStop : handleSend}
            disabled={disabled ? !onCancel || stopping : !canSend}
            title={
              stopping
                ? 'Stopping…'
                : disabled
                  ? 'Stop generating'
                  : 'Send (Enter)'
            }
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition active:scale-95 ${
              disabled
                ? 'bg-text-primary text-bg-base hover:opacity-90'
                : canSend
                  ? 'bg-primary text-on-primary shadow-soft hover:brightness-110'
                  : 'bg-bg-elevated text-text-dim'
            }`}
            aria-label={disabled ? 'Stop' : 'Send message'}
          >
            {disabled ? (
              stopping ? (
                <svg
                  className="animate-spin"
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
                </svg>
              ) : (
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                >
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                </svg>
              )
            ) : (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
              >
                <path
                  d="M12 19V5M5 12l7-7 7 7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
        </div>
        <p className="mt-2 text-center text-[11px] text-text-dim">
          Enter to send · Shift+Enter for a new line · Ogun AI can make
          mistakes, so verify important information.
        </p>
      </div>
    </div>
  )
}
