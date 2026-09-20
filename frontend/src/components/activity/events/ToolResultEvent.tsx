interface Props {
  tool: string
  success: boolean
  preview: string
}

export default function ToolResultEvent({ tool, success, preview }: Props) {
  return (
    <div className="flex items-start gap-2 px-4 py-1 mb-1">
      <span
        className={`text-xs mt-0.5 shrink-0 ${success ? 'text-success' : 'text-error'}`}
      >
        {success ? '✓' : '✕'}
      </span>
      <p className="text-[11px] text-text-dim truncate flex-1">
        <span className="font-mono">{tool}</span>: {preview}
      </p>
    </div>
  )
}
