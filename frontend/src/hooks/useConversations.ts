import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  fetchConversations,
  deleteConversation as apiDeleteConversation,
} from '../api/conversations'

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: fetchConversations,
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: apiDeleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}
