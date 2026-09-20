import { format } from 'date-fns'
import type { DocumentSummary } from '../../api/types'

interface Props {
  doc: DocumentSummary
  onDelete: () => void
  deleting: boolean
}

export default function DocumentCard({ doc, onDelete, deleting }: Props) {
  return (
    <div className="flex items-center justify-between bg-bg-surface border border-border rounded-lg px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xl shrink-0">📄</span>
        <div className="min-w-0">
          <p className="text-sm text-text-primary truncate">{doc.filename}</p>
          <p className="text-xs text-text-muted">
            #{doc.id} · {doc.total_pages ?? '—'} pages · {doc.total_chunks}{' '}
            chunks · {format(new Date(doc.created_at), 'MMM d, yyyy')}
          </p>
        </div>
      </div>
      <button
        onClick={onDelete}
        disabled={deleting}
        className="text-xs text-error hover:underline shrink-0 ml-3 disabled:opacity-50"
      >
        {deleting ? 'Deleting...' : 'Delete'}
      </button>
    </div>
  )
}
