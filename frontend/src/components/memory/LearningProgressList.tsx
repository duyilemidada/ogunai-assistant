import { useLearningProgress } from '../../hooks/useLearningProgress'
import TopicConfidenceBar from './TopicConfidenceBar'

export default function LearningProgressList() {
  const { data: topics, isLoading } = useLearningProgress()

  if (isLoading)
    return <p className="text-text-muted text-sm px-4 py-6">Loading...</p>
  if (!topics || topics.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-text-muted text-sm">
          No learning progress recorded yet.
        </p>
        <p className="text-text-dim text-xs mt-1">
          Ask the TutorAgent to teach you something to get started.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {topics.map((t) => (
        <TopicConfidenceBar key={t.id} item={t} />
      ))}
    </div>
  )
}
