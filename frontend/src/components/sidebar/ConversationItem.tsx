interface Props {
  title: string
  active: boolean
  onClick: () => void
  onDelete: () => void
}

export default function ConversationItem({
  title,
  active,
  onClick,
  onDelete,
}: Props) {
  return (
    <div
      className={`group relative flex items-center rounded-lg text-sm transition-colors ${
        active
          ? 'bg-bg-elevated text-text-primary'
          : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-primary" />
      )}
      <button
        onClick={onClick}
        className="min-w-0 flex-1 truncate px-3 py-2 text-left"
        title={title}
      >
        {title}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          if (window.confirm('Delete this conversation?')) onDelete()
        }}
        className="mr-1 shrink-0 rounded-md p-1.5 text-text-dim opacity-0 transition hover:bg-bg-base hover:text-error focus:opacity-100 group-hover:opacity-100"
        aria-label="Delete conversation"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path
            d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  )
}
