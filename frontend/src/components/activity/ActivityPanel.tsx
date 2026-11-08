import { useUiStore } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import ActivityFeed from './ActivityFeed'

function PanelHeader({
  isStreaming,
  onClose,
}: {
  isStreaming: boolean
  onClose: () => void
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-border px-4 py-3.5">
      <span className="relative flex h-2.5 w-2.5">
        {isStreaming && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        )}
        <span
          className={`relative inline-flex h-2.5 w-2.5 rounded-full ${isStreaming ? 'bg-primary' : 'bg-success'}`}
        />
      </span>
      <h2 className="flex-1 text-sm font-semibold text-text-primary">
        {isStreaming ? 'Working...' : 'Done'}
      </h2>
      <span className="text-[11px] uppercase tracking-wider text-text-dim">
        Activity
      </span>
      <button
        onClick={onClose}
        aria-label="Close activity panel"
        className="rounded-md p-1 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  )
}

export default function ActivityPanel() {
  const activityPanelOpen = useUiStore((s) => s.activityPanelOpen)
  const closeActivity = useUiStore((s) => s.closeActivity)
  const activityEvents = useChatStore((s) => s.activityEvents)
  const isStreaming = useChatStore((s) => s.isStreaming)

  return (
    <>
      {/* Desktop: right column, pushes layout */}
      <aside
        className={`hidden h-screen shrink-0 overflow-hidden border-l border-border bg-bg-surface transition-all duration-300 md:block ${
          activityPanelOpen ? 'w-80' : 'w-0 border-l-0'
        }`}
      >
        <div className="flex h-full w-80 flex-col">
          <PanelHeader isStreaming={isStreaming} onClose={closeActivity} />
          <div className="flex-1 overflow-y-auto">
            <ActivityFeed events={activityEvents} />
          </div>
        </div>
      </aside>

      {/* Mobile: bottom sheet — a right column makes no sense on a narrow screen */}
      {activityPanelOpen && (
        <div className="anim-fade-up fixed inset-x-0 bottom-0 z-40 flex max-h-[60vh] flex-col rounded-t-2xl border-t border-border bg-bg-surface shadow-pop md:hidden">
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-border" />
          <PanelHeader isStreaming={isStreaming} onClose={closeActivity} />
          <div className="flex-1 overflow-y-auto">
            <ActivityFeed events={activityEvents} />
          </div>
        </div>
      )}
    </>
  )
}
