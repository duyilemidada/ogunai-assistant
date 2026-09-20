import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../api/types'

interface AuthState {
  token: string | null
  user: User | null
  setAuth: (token: string, user: User | null) => void
  logout: () => void
}

// persist() writes to localStorage automatically under the 'ogun-auth' key.
// This is the ONE deliberate exception to "no localStorage in shared code" —
// auth persistence across refreshes is expected here, and Zustand's persist
// middleware is the standard, RN-portable way to do it (swaps to AsyncStorage
// with one line when we build the mobile app).
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: 'ogun-auth' },
  ),
)
