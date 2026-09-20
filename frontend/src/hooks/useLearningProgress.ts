import { useQuery } from '@tanstack/react-query'
import { fetchLearningProgress } from '../api/memory'

export function useLearningProgress() {
  return useQuery({
    queryKey: ['learning'],
    queryFn: fetchLearningProgress,
  })
}
