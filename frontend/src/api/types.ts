// Shared types — ports unchanged into the future React Native app.

export interface User {
  id: number
  email: string
  full_name: string | null
  role: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface Message {
  id?: number
  role: 'user' | 'supervisor' | 'assistant' | 'tool'
  agent_name?: string | null
  content: string
  tool_calls?: unknown
  created_at?: string
}

export interface ChatRequest {
  message: string
  conversation_id?: number | null
}

export interface ChatResponse extends Message {
  id: number
  conversation_id: number
  created_at: string
}

export interface ApiError {
  error: {
    code: string
    message?: string
    details?: unknown
  }
}

export interface ActivityEvent {
  id: string
  type:
    | 'thinking'
    | 'tool_call'
    | 'tool_result'
    | 'specialist_start'
    | 'specialist_done'
    | 'agent_done'
    | 'error'
  timestamp: number
  agent?: string
  specialist?: string
  tool?: string
  args?: Record<string, string>
  success?: boolean
  preview?: string
  instruction_preview?: string
  message?: string
  iteration?: number
  max_iterations?: number
}

// --- Phase 4 ---

export interface ConversationSummary {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface DocumentSummary {
  id: number
  filename: string
  total_pages: number | null
  total_chunks: number
  created_at: string
}

export interface LearningProgressItem {
  id: number
  topic: string
  confidence: number
  updated_at: string
}

export interface UploadResponse {
  message: string
  document_id: number
  filename: string
  total_pages: number
  total_chunks: number
  usage: string
}
