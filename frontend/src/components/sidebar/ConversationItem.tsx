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
      className={`group flex items-center rounded-lg text-sm transition-colors ${
        active
          ? 'bg-bg-elevated text-text-primary'
          : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
      }`}
    >
      <button
        onClick={onClick}
        className="flex-1 text-left px-3 py-2 truncate min-w-0"
      >
        {title}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          onDelete()
        }}
        className="opacity-0 group-hover:opacity-100 shrink-0 pr-2 text-text-dim hover:text-error transition-opacity"
        aria-label="Delete conversation"
      >
        ✕
      </button>
    </div>
  )
}
