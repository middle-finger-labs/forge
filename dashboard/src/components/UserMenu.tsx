import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, User } from 'lucide-react'
import { useSession, signOut } from '../lib/auth.ts'

export default function UserMenu() {
  const { data: session } = useSession()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  if (!session?.user) return null

  const user = session.user
  const initials = (user.name ?? user.email ?? '?')
    .split(' ')
    .map((w: string) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-300 transition hover:bg-slate-800"
      >
        {user.image ? (
          <img
            src={user.image}
            alt=""
            className="h-6 w-6 rounded-full object-cover"
          />
        ) : (
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-700 text-[10px] font-bold text-slate-300">
            {initials}
          </div>
        )}
        <span className="hidden max-w-[100px] truncate sm:inline">
          {user.name ?? user.email}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-48 rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
          <div className="border-b border-slate-800 px-3 py-2">
            <p className="truncate text-sm font-medium text-slate-200">{user.name}</p>
            <p className="truncate text-xs text-slate-500">{user.email}</p>
          </div>
          <button
            onClick={() => {
              setOpen(false)
              navigate('/settings')
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          >
            <User className="h-3.5 w-3.5" />
            Settings
          </button>
          <button
            onClick={handleSignOut}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-400 transition hover:bg-slate-800 hover:text-red-300"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
