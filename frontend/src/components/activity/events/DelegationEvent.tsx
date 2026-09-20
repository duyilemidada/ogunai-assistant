export default function DelegationEvent({
  specialist,
  preview,
}: {
  specialist: string
  preview?: string
}) {
  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2">
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-accent shrink-0"
        >
          <path
            d="M5 12h14M13 6l6 6-6 6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="text-xs text-text-primary font-medium">
          Supervisor → {specialist}
        </span>
      </div>
      {preview && (
        <p className="text-[11px] text-text-dim pl-5 mt-0.5 truncate">
          {preview}
        </p>
      )}
    </div>
  )
}
