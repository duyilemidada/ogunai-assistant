interface Props {
  documentId: number
  filename: string
  onRemove: () => void
}

export default function AttachedDocumentChip({
  documentId,
  filename,
  onRemove,
}: Props) {
  return (
    <div className="anim-fade-up flex items-center gap-2 rounded-lg border border-border bg-bg-elevated py-1 pl-2 pr-1 text-xs shadow-soft">
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="shrink-0 text-primary"
      >
        <path
          d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"
          strokeLinejoin="round"
        />
        <path d="M14 3v5h5" strokeLinejoin="round" />
      </svg>
      <span className="max-w-[160px] truncate text-text-primary">
        {filename}
      </span>
      <span className="text-text-dim">#{documentId}</span>
      <button
        onClick={onRemove}
        className="rounded p-1 text-text-muted transition-colors hover:bg-bg-hover hover:text-error"
        aria-label="Remove attachment"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  )
}
