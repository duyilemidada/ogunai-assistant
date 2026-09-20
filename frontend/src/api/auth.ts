import { apiClient } from './client'
import type {
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  User,
} from './types'

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await apiClient.post<TokenResponse>('/auth/login', data)
  return res.data
}

export async function register(data: RegisterRequest): Promise<User> {
  const res = await apiClient.post<User>('/auth/register', data)
  return res.data
}
