import { format } from 'date-fns'
import type { LearningProgressItem } from '../../api/types'

const LABELS: Record<number, string> = {
  1: 'Just heard of it',
  2: 'Basic idea',
  3: 'Comfortable',
  4: 'Solid',
  5: 'Could teach it',
}

export default function TopicConfidenceBar({
  item,
}: {
  item: LearningProgressItem
}) {
  return (
    <div className="bg-bg-surface border border-border rounded-lg px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-text-primary capitalize">
          {item.topic}
        </span>
        <span className="text-xs text-text-muted">
          {format(new Date(item.updated_at), 'MMM d')}
        </span>
      </div>
      <div className="flex gap-1 mb-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <div
            key={n}
            className={`h-1.5 flex-1 rounded-full ${n <= item.confidence ? 'bg-primary' : 'bg-bg-elevated'}`}
          />
        ))}
      </div>
      <p className="text-[11px] text-text-dim">{LABELS[item.confidence]}</p>
    </div>
  )
}
