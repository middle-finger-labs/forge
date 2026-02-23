import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, Eye, EyeOff } from 'lucide-react'
import { signUp } from '../lib/auth.ts'

export default function SignupPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const passwordsMatch = password === confirmPassword
  const passwordLongEnough = password.length >= 8

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password || !name.trim()) return

    if (!passwordLongEnough) {
      setError('Password must be at least 8 characters')
      return
    }
    if (!passwordsMatch) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const result = await signUp.email({
        email: email.trim(),
        password,
        name: name.trim(),
      })
      if (result.error) {
        setError(result.error.message ?? 'Signup failed')
      } else {
        // Signup success — redirect to pipeline list
        // If the user was invited via link, Better Auth auto-joins the org
        navigate('/')
      }
    } catch {
      setError('Unable to connect to auth service')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        {/* Branding */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex items-center gap-2">
            <Zap className="h-7 w-7 text-cyan-400" />
            <span className="text-2xl font-bold tracking-tight text-slate-100">Forge</span>
          </div>
          <p className="text-sm text-slate-500">Create your account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-slate-300">
              Name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
              autoComplete="name"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 transition focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
              placeholder="Your name"
            />
          </div>

          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-slate-300">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 transition focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-slate-300">
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="new-password"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 pr-10 text-sm text-slate-100 placeholder-slate-500 transition focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
                placeholder="At least 8 characters"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="confirm-password" className="mb-1.5 block text-sm font-medium text-slate-300">
              Confirm Password
            </label>
            <input
              id="confirm-password"
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 transition focus:border-cyan-600 focus:outline-none focus:ring-1 focus:ring-cyan-600"
              placeholder="Repeat password"
            />
            {confirmPassword && !passwordsMatch && (
              <p className="mt-1 text-xs text-red-400">Passwords do not match</p>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !email.trim() || !password || !name.trim() || !passwordsMatch}
            className="w-full rounded-lg bg-cyan-600 py-2.5 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? 'Creating account...' : 'Create account'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-500">
          Already have an account?{' '}
          <Link to="/login" className="text-cyan-400 hover:text-cyan-300">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
