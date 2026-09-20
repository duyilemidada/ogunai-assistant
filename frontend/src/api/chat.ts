import { apiClient } from './client'
import type { ChatRequest, ChatResponse } from './types'

export async function sendMessage(data: ChatRequest): Promise<ChatResponse> {
  // Trailing slash matters — without it FastAPI 307-redirects, adding a round trip.
  const res = await apiClient.post<ChatResponse>('/chat/', data)
  return res.data
}
