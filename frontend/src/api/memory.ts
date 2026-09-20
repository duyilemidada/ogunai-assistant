import { apiClient } from './client'
import type {
  DocumentSummary,
  LearningProgressItem,
  UploadResponse,
} from './types'

export async function fetchDocuments(): Promise<DocumentSummary[]> {
  const res = await apiClient.get<DocumentSummary[]>('/memory/documents')
  return res.data
}

export async function deleteDocument(id: number): Promise<void> {
  await apiClient.delete(`/memory/documents/${id}`)
}

export async function fetchLearningProgress(): Promise<LearningProgressItem[]> {
  const res = await apiClient.get<LearningProgressItem[]>('/memory/learning')
  return res.data
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  // No headers override here — axios detects the FormData body and sets
  // 'Content-Type: multipart/form-data; boundary=...' automatically.
  // Setting the header manually (as before) strips the boundary parameter,
  // which the backend needs to split the multipart body into parts.
  const res = await apiClient.post<UploadResponse>('/chat/upload', formData)
  return res.data
}
