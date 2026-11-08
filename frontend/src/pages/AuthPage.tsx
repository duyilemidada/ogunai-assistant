import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

const inputClass =
  'w-full rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition placeholder:text-text-dim focus:border-primary/60 focus:ring-4 focus:ring-primary/10'

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
    <div className="ambient-bg flex min-h-screen items-center justify-center bg-bg-base px-4">
      <div className="anim-fade-up w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="brand-gradient mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl shadow-pop">
            <span className="text-xl font-bold text-on-primary">O</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Ogun AI
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            {mode === 'login'
              ? 'Welcome back. Sign in to continue.'
              : 'Create your account.'}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-2xl border border-border bg-bg-surface p-6 shadow-pop"
        >
          {mode === 'register' && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-muted">
                Full name (optional)
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={inputClass}
                placeholder="Your name"
              />
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-muted">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-muted">
              Password
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
              placeholder="At least 8 characters"
            />
          </div>

          {error && (
            <div className="rounded-xl border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="brand-gradient w-full rounded-xl py-2.5 text-sm font-semibold text-on-primary shadow-soft transition hover:brightness-110 active:scale-[0.99] disabled:opacity-50"
          >
            {loading
              ? 'Please wait...'
              : mode === 'login'
                ? 'Sign in'
                : 'Create account'}
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-text-muted">
          {mode === 'login'
            ? "Don't have an account? "
            : 'Already have an account? '}
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
            className="font-medium text-accent hover:underline"
          >
            {mode === 'login' ? 'Register' : 'Sign in'}
          </button>
        </p>
      </div>
    </div>
  )
}
