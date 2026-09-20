import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import AuthPage from './pages/AuthPage'
import ChatPage from './pages/ChatPage'
import MemoryPage from './pages/MemoryPage'

function AuthGuard() {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <Outlet />
}

export const router = createBrowserRouter([
  { path: '/login', element: <AuthPage /> },
  {
    element: <AuthGuard />,
    children: [
      { path: '/chat', element: <ChatPage /> },
      { path: '/memory', element: <MemoryPage /> },
      { path: '/', element: <Navigate to="/chat" replace /> },
    ],
  },
])
