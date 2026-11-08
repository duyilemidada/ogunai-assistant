export default function TypingIndicator() {
  return (
    <div className="anim-fade-up px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <div className="brand-gradient flex h-6 w-6 animate-pulse items-center justify-center rounded-full">
          <span className="text-[11px] font-bold text-on-primary">O</span>
        </div>
        <span className="text-xs font-semibold text-text-muted">Ogun AI</span>
      </div>
      <div className="flex items-center gap-2 pl-8">
        <span className="flex gap-1">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
        </span>
        <span className="text-xs text-text-dim">
          Working. Follow along in the activity panel.
        </span>
      </div>
    </div>
  )
}
