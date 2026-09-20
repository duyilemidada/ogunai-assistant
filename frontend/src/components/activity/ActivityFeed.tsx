import type { ActivityEvent } from '../../api/types'
import ThinkingEvent from './events/ThinkingEvent'
import DelegationEvent from './events/DelegationEvent'
import AgentDoneEvent from './events/AgentDoneEvent'
import ToolCallEvent from './events/ToolCallEvent'
import ToolResultEvent from './events/ToolResultEvent'
import ErrorEvent from './events/ErrorEvent'

export default function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-text-dim text-xs px-3 py-4 text-center">
        Waiting for the agent...
      </p>
    )
  }

  return (
    <div className="py-2">
      {events.map((e) => {
        switch (e.type) {
          case 'thinking':
            return <ThinkingEvent key={e.id} agent={e.agent!} />
          case 'specialist_start':
            return (
              <DelegationEvent
                key={e.id}
                specialist={e.specialist!}
                preview={e.instruction_preview}
              />
            )
          case 'specialist_done':
          case 'agent_done':
            return (
              <AgentDoneEvent
                key={e.id}
                agent={e.specialist || e.agent || 'Agent'}
              />
            )
          case 'tool_call':
            return (
              <ToolCallEvent
                key={e.id}
                agent={e.agent!}
                tool={e.tool!}
                args={e.args || {}}
              />
            )
          case 'tool_result':
            return (
              <ToolResultEvent
                key={e.id}
                tool={e.tool!}
                success={!!e.success}
                preview={e.preview || ''}
              />
            )
          case 'error':
            return (
              <ErrorEvent key={e.id} message={e.message || 'Unknown error'} />
            )
          default:
            return null
        }
      })}
    </div>
  )
}
