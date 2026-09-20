import { apiClient } from './client'
import type { ConversationSummary, Message } from './types'

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const res = await apiClient.get<ConversationSummary[]>('/conversations/')
  return res.data
}

export async function fetchConversationMessages(
  id: number,
): Promise<Message[]> {
  const res = await apiClient.get<Message[]>(`/conversations/${id}/messages`)
  return res.data
}

export async function deleteConversation(id: number): Promise<void> {
  await apiClient.delete(`/conversations/${id}`)
}
