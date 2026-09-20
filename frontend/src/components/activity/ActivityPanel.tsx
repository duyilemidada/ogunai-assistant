import { useUiStore } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import ActivityFeed from './ActivityFeed'

export default function ActivityPanel() {
  const activityPanelOpen = useUiStore((s) => s.activityPanelOpen)
  const activityEvents = useChatStore((s) => s.activityEvents)
  const isStreaming = useChatStore((s) => s.isStreaming)

  return (
    <>
      {/* Desktop: right column, pushes layout */}
      <aside
        className={`hidden md:block shrink-0 bg-bg-surface border-l border-border h-screen overflow-hidden transition-all duration-300 ${
          activityPanelOpen ? 'w-80' : 'w-0 border-l-0'
        }`}
      >
        <div className="w-80 h-full flex flex-col">
          <div className="px-4 py-4 border-b border-border flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-primary animate-pulse' : 'bg-success'}`}
            />
            <h2 className="text-sm font-semibold text-text-primary">
              {isStreaming ? 'Working...' : 'Done'}
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto">
            <ActivityFeed events={activityEvents} />
          </div>
        </div>
      </aside>

      {/* Mobile: bottom sheet — a right column makes no sense on a narrow screen */}
      {activityPanelOpen && (
        <div className="md:hidden fixed inset-x-0 bottom-0 z-40 bg-bg-surface border-t border-border rounded-t-2xl max-h-[60vh] flex flex-col shadow-2xl">
          <div className="px-4 py-3 border-b border-border flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-primary animate-pulse' : 'bg-success'}`}
            />
            <h2 className="text-sm font-semibold text-text-primary">
              {isStreaming ? 'Working...' : 'Done'}
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto">
            <ActivityFeed events={activityEvents} />
          </div>
        </div>
      )}
    </>
  )
}
