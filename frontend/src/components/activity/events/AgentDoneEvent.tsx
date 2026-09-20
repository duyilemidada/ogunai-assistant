export default function AgentDoneEvent({ agent }: { agent: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-success shrink-0"
      >
        <path
          d="M20 6 9 17l-5-5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-xs text-text-muted">{agent} finished</span>
    </div>
  )
}
