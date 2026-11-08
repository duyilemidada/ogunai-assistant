// Renders the code-written "Waiting for your approval" footer that the backend
// appends to a reply. Commands are shown verbatim in monospace and are never
// run through the Markdown renderer, so what you read is exactly what runs.

export interface ParsedApproval {
  body: string
  items: { label: string; text: string }[]
  footer: string
}

const MARKERS = [
  'Waiting for your approval (nothing has run yet):',
  'Waiting for approval:',
]
const KNOWN_LABELS = ['transfer', 'command', 'github']

export function parseApproval(content: string): ParsedApproval | null {
  let idx = -1
  let markerLen = 0
  for (const m of MARKERS) {
    const i = content.lastIndexOf(m)
    if (i > idx) {
      idx = i
      markerLen = m.length
    }
  }
  if (idx === -1) return null

  const items: { label: string; text: string }[] = []
  const footerLines: string[] = []
  for (const line of content.slice(idx + markerLen).split('\n')) {
    const item = /^- ([A-Za-z_]+): ([\s\S]*)$/.exec(line)
    if (item) {
      items.push({ label: item[1], text: item[2] })
    } else if (/^(Reply |More than one)/.test(line)) {
      footerLines.push(line)
    } else if (line.trim()) {
      if (footerLines.length) footerLines.push(line)
      else if (items.length) items[items.length - 1].text += '\n' + line
    }
  }
  if (items.length === 0) return null
  return {
    body: content.slice(0, idx).trimEnd(),
    items,
    footer: footerLines.join(' '),
  }
}

export default function ApprovalNotice({
  items,
  footer,
  onReply,
}: {
  items: ParsedApproval['items']
  footer: string
  onReply?: (text: string) => void
}) {
  const single = items.length === 1
  const replies: { text: string; send: string }[] = single
    ? [{ text: 'Approve', send: 'approve' }]
    : items
        .filter((i) => KNOWN_LABELS.includes(i.label))
        .map((i) => ({
          text: `Approve ${i.label}`,
          send: `approve ${i.label}`,
        }))

  return (
    <div className="anim-fade-up mt-4 rounded-xl border border-warning/40 bg-warning/10 p-3.5">
      <div className="flex flex-wrap items-center gap-x-2 text-warning">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M12 3 4 6v6c0 4.5 3.2 7.8 8 9 4.8-1.2 8-4.5 8-9V6l-8-3Z"
            strokeLinejoin="round"
          />
          <path d="M12 8v4M12 15.5v.01" strokeLinecap="round" />
        </svg>
        <span className="text-[13px] font-semibold">
          Waiting for your approval
        </span>
        <span className="text-xs text-text-muted">nothing has run yet</span>
      </div>
      <ul className="mt-3 space-y-2">
        {items.map((it, i) => (
          <li
            key={i}
            className="rounded-lg border border-border bg-bg-base/60 p-2.5"
          >
            <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warning">
              {it.label}
            </span>
            <pre className="mt-1.5 whitespace-pre-wrap break-all font-mono text-[12.5px] leading-relaxed text-text-primary">
              {it.text}
            </pre>
          </li>
        ))}
      </ul>
      {footer && (
        <p className="mt-3 text-xs leading-relaxed text-text-muted">{footer}</p>
      )}
      {onReply && replies.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {replies.map((r) => (
            <button
              key={r.send}
              onClick={() => onReply(r.send)}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary transition hover:brightness-110 active:scale-[0.98]"
            >
              {r.text}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
