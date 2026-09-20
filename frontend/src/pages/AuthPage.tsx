import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

export default function AuthPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const setAuth = useAuthStore((s) => s.setAuth)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      if (mode === 'register') {
        await register({ email, password, full_name: fullName || undefined })
        // Registration doesn't return a token — log in immediately after.
      }
      const { access_token } = await login({ email, password })
      // The backend has no GET /auth/me yet, so we don't have a full User
      // object here — store what we know (email) and refine when that
      // endpoint exists. Doesn't block anything in Phase 1/2.
      setAuth(access_token, { id: 0, email, full_name: null, role: 'user' })
      navigate('/chat')
    } catch (err: any) {
      const detail =
        err?.response?.data?.error?.message ||
        err?.response?.data?.error?.details?.[0]?.msg ||
        'Something went wrong. Check your details and try again.'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-base px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">
            Ogun AI
          </h1>
          <p className="text-text-muted text-sm mt-1">
            {mode === 'login' ? 'Sign in to continue' : 'Create your account'}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-bg-surface border border-border rounded-xl p-6 space-y-4"
        >
          {mode === 'register' && (
            <div>
              <label className="block text-xs text-text-muted mb-1.5">
                Full name (optional)
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2
                           text-text-primary text-sm focus:outline-none focus:border-accent"
                placeholder="Israel Duyilemi"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-text-muted mb-1.5">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2
                         text-text-primary text-sm focus:outline-none focus:border-accent"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-xs text-text-muted mb-1.5">
              Password
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2
                         text-text-primary text-sm focus:outline-none focus:border-accent"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="text-error text-xs bg-error/10 border border-error/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-primary hover:bg-primary/90 disabled:opacity-50
                       text-white font-medium text-sm rounded-lg py-2.5 transition-colors"
          >
            {loading
              ? 'Please wait...'
              : mode === 'login'
                ? 'Sign in'
                : 'Create account'}
          </button>
        </form>

        <p className="text-center text-text-muted text-xs mt-4">
          {mode === 'login'
            ? "Don't have an account? "
            : 'Already have an account? '}
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
            className="text-accent hover:underline"
          >
            {mode === 'login' ? 'Register' : 'Sign in'}
          </button>
        </p>
      </div>
    </div>
  )
}
