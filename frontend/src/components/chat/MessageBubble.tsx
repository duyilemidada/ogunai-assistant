import { useState } from 'react'
import type { Message } from '../../api/types'
import MarkdownRenderer from './MarkdownRenderer'
import ApprovalNotice, { parseApproval } from './ApprovalNotice'

interface Props {
  message: Message
  /** True only for the newest reply while nothing is streaming. */
  canReply?: boolean
  onQuickReply?: (text: string) => void
}

const ATTACHMENT = /^\[Attached: document (\d+) — (.+)\]$/

// ChatInput prefixes "[Attached: document N — file.pdf]" lines; show them as chips.
function splitAttachments(content: string) {
  const lines = content.split('\n')
  const files: { id: string; name: string }[] = []
  let i = 0
  while (i < lines.length) {
    const m = ATTACHMENT.exec(lines[i])
    if (!m) break
    files.push({ id: m[1], name: m[2] })
    i++
  }
  return { files, text: lines.slice(i).join('\n') }
}

export default function MessageBubble({
  message,
  canReply,
  onQuickReply,
}: Props) {
  const [copied, setCopied] = useState(false)

  if (message.role === 'user') {
    const { files, text } = splitAttachments(message.content)
    return (
      <div className="anim-fade-up flex justify-end px-4 py-2">
        <div className="bubble-user max-w-[78%] rounded-2xl rounded-br-md px-4 py-2.5 shadow-soft">
          {files.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {files.map((f) => (
                <span
                  key={f.id}
                  className="inline-flex max-w-[220px] items-center gap-1.5 rounded-md border border-border bg-bg-base/60 px-2 py-1 text-xs text-text-muted"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path
                      d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"
                      strokeLinejoin="round"
                    />
                    <path d="M14 3v5h5" strokeLinejoin="round" />
                  </svg>
                  <span className="truncate">{f.name}</span>
                </span>
              ))}
            </div>
          )}
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-text-primary">
            {text}
          </p>
        </div>
      </div>
    )
  }

  const approval = parseApproval(message.content)
  const body = approval ? approval.body : message.content
  const stopped = body.startsWith('Stopped before I finished')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(body)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable on plain HTTP; the code blocks have a fallback */
    }
  }

  return (
    <div className="anim-fade-up group px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <div className="brand-gradient flex h-6 w-6 items-center justify-center rounded-full shadow-soft">
          <span className="text-[11px] font-bold text-on-primary">O</span>
        </div>
        <span className="text-xs font-semibold text-text-muted">Ogun AI</span>
      </div>
      <div className="pl-8">
        {stopped ? (
          <p className="flex items-center gap-2 text-sm italic text-text-muted">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
              <rect x="5" y="5" width="14" height="14" rx="2" />
            </svg>
            {body}
          </p>
        ) : (
          body && <MarkdownRenderer content={body} />
        )}
        {approval && (
          <ApprovalNotice
            items={approval.items}
            footer={approval.footer}
            onReply={canReply ? onQuickReply : undefined}
          />
        )}
        {!stopped && body && (
          <div className="mt-2 flex opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <button
              onClick={copy}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-dim transition-colors hover:bg-bg-hover hover:text-text-primary"
              aria-label="Copy reply"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
