import axios from 'axios'
import { useAuthStore } from '../stores/authStore'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  // No default Content-Type here. Axios sets 'application/json' automatically
  // for plain object bodies, and 'multipart/form-data' (with the correct
  // boundary) automatically for FormData bodies. A hardcoded default here
  // would take precedence over that per-request detection and break uploads.
})

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export { API_BASE_URL }
