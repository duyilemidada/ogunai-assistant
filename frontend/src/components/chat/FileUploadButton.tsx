import { useRef, useState } from 'react'
import { useUploadDocument } from '../../hooks/useDocuments'

interface Props {
  onUploaded: (documentId: number, filename: string) => void
}

export default function FileUploadButton({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const { mutateAsync, isPending } = useUploadDocument()

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are supported.')
      e.target.value = ''
      return
    }

    try {
      const result = await mutateAsync(file)
      onUploaded(result.document_id, result.filename)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Upload failed. Try again.')
    } finally {
      e.target.value = ''
    }
  }

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        onChange={handleChange}
        className="hidden"
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={isPending}
        className="shrink-0 w-8 h-8 rounded-lg text-text-muted hover:text-text-primary
                   hover:bg-bg-hover flex items-center justify-center transition-colors disabled:opacity-50"
        aria-label="Attach PDF"
        title="Attach a PDF"
      >
        {isPending ? (
          <svg
            className="animate-spin"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              d="M21.44 11.05 12.25 20.24a5 5 0 0 1-7.07-7.07l8.49-8.49a3 3 0 0 1 4.24 4.24l-8.49 8.49a1 1 0 0 1-1.41-1.41l7.78-7.78"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </button>
      {error && (
        <div className="absolute bottom-10 left-0 bg-error/10 border border-error/30 text-error text-[11px] rounded-lg px-2 py-1 whitespace-nowrap">
          {error}
        </div>
      )}
    </div>
  )
}
