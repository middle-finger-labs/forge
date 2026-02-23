import clsx from 'clsx'
import type { PresenceUser } from '../hooks/useWebSocket.ts'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(name: string | undefined, email: string | undefined): string {
  const src = name ?? email ?? '?'
  return src
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

const AVATAR_COLORS = [
  'bg-cyan-700',
  'bg-emerald-700',
  'bg-amber-700',
  'bg-purple-700',
  'bg-rose-700',
  'bg-blue-700',
  'bg-teal-700',
  'bg-orange-700',
]

function colorForUser(userId: string): string {
  let hash = 0
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

// ---------------------------------------------------------------------------
// Avatar component
// ---------------------------------------------------------------------------

function PresenceAvatar({
  user,
  isAway,
  size = 'sm',
}: {
  user: PresenceUser
  isAway?: boolean
  size?: 'sm' | 'md'
}) {
  const initials = getInitials(user.user_name, user.email)
  const sizeClass = size === 'md' ? 'h-7 w-7 text-[11px]' : 'h-6 w-6 text-[10px]'

  return (
    <div className="group relative" title={`${user.user_name}${isAway ? ' (away)' : ''}`}>
      <div
        className={clsx(
          'flex items-center justify-center rounded-full font-bold text-white ring-2 ring-slate-950 transition-opacity',
          colorForUser(user.user_id),
          sizeClass,
          isAway && 'opacity-50',
        )}
      >
        {initials}
      </div>

      {/* Online/away indicator dot */}
      <span
        className={clsx(
          'absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-slate-950',
          isAway ? 'bg-amber-500' : 'bg-emerald-500',
        )}
      />

      {/* Tooltip */}
      <div className="pointer-events-none absolute -bottom-8 left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {user.user_name || user.email}
        {isAway && <span className="ml-1 text-amber-400">(away)</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface PresenceBarProps {
  users: PresenceUser[]
  currentUserId?: string
  className?: string
}

export default function PresenceBar({ users, currentUserId, className }: PresenceBarProps) {
  if (users.length === 0) return null

  // Sort: current user first, then others alphabetically
  const sorted = [...users].sort((a, b) => {
    if (a.user_id === currentUserId) return -1
    if (b.user_id === currentUserId) return 1
    return (a.user_name ?? '').localeCompare(b.user_name ?? '')
  })

  const maxVisible = 6
  const visible = sorted.slice(0, maxVisible)
  const overflow = sorted.length - maxVisible

  return (
    <div className={clsx('flex items-center gap-1', className)}>
      {/* Stacked avatars */}
      <div className="flex -space-x-1.5">
        {visible.map((user) => (
          <PresenceAvatar
            key={user.user_id}
            user={user}
            isAway={user.status === 'away'}
          />
        ))}
      </div>

      {/* Overflow count */}
      {overflow > 0 && (
        <span className="ml-1 text-xs text-slate-500">+{overflow}</span>
      )}

      {/* Count label */}
      <span className="ml-1 text-xs text-slate-600">
        {users.length} online
      </span>
    </div>
  )
}
