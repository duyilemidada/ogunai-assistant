export default function ThinkingEvent({ agent }: { agent: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse shrink-0" />
      <span className="text-xs text-text-muted">{agent} is thinking...</span>
    </div>
  )
}
