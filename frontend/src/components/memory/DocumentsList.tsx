import { useDocuments, useDeleteDocument } from '../../hooks/useDocuments'
import DocumentCard from './DocumentCard'

export default function DocumentsList() {
  const { data: documents, isLoading } = useDocuments()
  const { mutate: remove, isPending, variables } = useDeleteDocument()

  if (isLoading)
    return <p className="text-text-muted text-sm px-4 py-6">Loading...</p>
  if (!documents || documents.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-text-muted text-sm">No documents uploaded yet.</p>
        <p className="text-text-dim text-xs mt-1">
          Attach a PDF from the chat input to get started.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {documents.map((doc) => (
        <DocumentCard
          key={doc.id}
          doc={doc}
          onDelete={() => remove(doc.id)}
          deleting={isPending && variables === doc.id}
        />
      ))}
    </div>
  )
}
