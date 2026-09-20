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
    <div className="flex items-center gap-1.5 bg-bg-elevated border border-border rounded-lg pl-2 pr-1 py-1 text-xs">
      <span>📄</span>
      <span className="text-text-primary truncate max-w-[140px]">
        {filename}
      </span>
      <span className="text-text-dim">#{documentId}</span>
      <button
        onClick={onRemove}
        className="text-text-muted hover:text-error px-1"
        aria-label="Remove attachment"
      >
        ✕
      </button>
    </div>
  )
}
