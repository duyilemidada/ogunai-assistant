export default function TypingIndicator() {
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center animate-pulse">
          <span className="text-[10px] font-bold text-white">O</span>
        </div>
        <span className="text-xs text-text-muted font-medium">
          Ogun AI is working...
        </span>
      </div>
      <div className="pl-7 flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:-0.3s]" />
        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:-0.15s]" />
        <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" />
      </div>
    </div>
  )
}
