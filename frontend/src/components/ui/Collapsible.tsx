import { useState, type ReactNode } from 'react'

interface Props {
  summary: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}

export default function Collapsible({
  summary,
  children,
  defaultOpen = false,
}: Props) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-left gap-2"
      >
        {summary}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`shrink-0 text-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  )
}
