import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Building2,
  Check,
  ChevronDown,
  Plus,
  UserPlus,
  X,
} from 'lucide-react'
import { organization, useActiveOrganization, useListOrganizations } from '../lib/auth.ts'

// ---------------------------------------------------------------------------
// Create Org Modal
// ---------------------------------------------------------------------------

function CreateOrgModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  // Auto-generate slug from name
  useEffect(() => {
    setSlug(
      name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, ''),
    )
  }, [name])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await organization.create({ name: name.trim(), slug })
      if (result.error) {
        setError(result.error.message ?? 'Failed to create organization')
      } else {
        onClose()
      }
    } catch {
      setError('Failed to create organization')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      ref={backdropRef}
      onClick={(e) => e.target === backdropRef.current && onClose()}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-100">Create Organization</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3 px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              placeholder="My Team"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Slug</label>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-sm text-slate-100 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              placeholder="my-team"
            />
          </div>
          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading || !name.trim()}
            className="w-full rounded-lg bg-cyan-600 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {loading ? 'Creating...' : 'Create'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Invite Member Modal
// ---------------------------------------------------------------------------

function InviteMemberModal({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'member' | 'admin'>('member')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const backdropRef = useRef<HTMLDivElement>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await organization.inviteMember({
        email: email.trim(),
        role,
      })
      if (result.error) {
        setError(result.error.message ?? 'Failed to send invite')
      } else {
        setSuccess(true)
        setTimeout(onClose, 1500)
      }
    } catch {
      setError('Failed to send invite')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      ref={backdropRef}
      onClick={(e) => e.target === backdropRef.current && onClose()}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-100">Invite Member</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3 px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              placeholder="colleague@example.com"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Role</label>
            <div className="flex gap-3">
              {(['member', 'admin'] as const).map((r) => (
                <label key={r} className="flex items-center gap-1.5 text-sm text-slate-300">
                  <input
                    type="radio"
                    checked={role === r}
                    onChange={() => setRole(r)}
                    className="accent-cyan-500"
                  />
                  {r.charAt(0).toUpperCase() + r.slice(1)}
                </label>
              ))}
            </div>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          {success && <p className="text-xs text-emerald-400">Invitation sent!</p>}
          <button
            type="submit"
            disabled={loading || !email.trim() || success}
            className="w-full rounded-lg bg-cyan-600 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {loading ? 'Sending...' : 'Send Invite'}
          </button>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// OrgSwitcher
// ---------------------------------------------------------------------------

export default function OrgSwitcher() {
  const { data: activeOrg } = useActiveOrganization()
  const { data: orgList } = useListOrganizations()
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showInvite, setShowInvite] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const switchOrg = useCallback(
    async (orgId: string) => {
      await organization.setActive({ organizationId: orgId })
      setOpen(false)
      // Reload to re-fetch org-scoped data
      window.location.reload()
    },
    [],
  )

  const isAdmin =
    activeOrg?.members?.some(
      (m: { role: string }) => m.role === 'owner' || m.role === 'admin',
    ) ?? false

  return (
    <>
      <div ref={dropdownRef} className="relative">
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
        >
          <Building2 className="h-3.5 w-3.5 text-slate-500" />
          <span className="max-w-[120px] truncate">
            {activeOrg?.name ?? 'No org'}
          </span>
          <ChevronDown className="h-3 w-3 text-slate-500" />
        </button>

        {open && (
          <div className="absolute right-0 top-full z-50 mt-1.5 w-56 rounded-lg border border-slate-700 bg-slate-900 py-1 shadow-xl">
            {/* Org list */}
            {orgList?.map((org: { id: string; name: string }) => (
              <button
                key={org.id}
                onClick={() => switchOrg(org.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 transition hover:bg-slate-800"
              >
                <Building2 className="h-3.5 w-3.5 text-slate-500" />
                <span className="flex-1 truncate">{org.name}</span>
                {activeOrg?.id === org.id && (
                  <Check className="h-3.5 w-3.5 text-cyan-400" />
                )}
              </button>
            ))}

            <div className="my-1 border-t border-slate-800" />

            {/* Create org */}
            <button
              onClick={() => {
                setOpen(false)
                setShowCreate(true)
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
            >
              <Plus className="h-3.5 w-3.5" />
              Create Organization
            </button>

            {/* Invite member (admin/owner only) */}
            {isAdmin && (
              <button
                onClick={() => {
                  setOpen(false)
                  setShowInvite(true)
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
              >
                <UserPlus className="h-3.5 w-3.5" />
                Invite Member
              </button>
            )}
          </div>
        )}
      </div>

      {showCreate && <CreateOrgModal onClose={() => setShowCreate(false)} />}
      {showInvite && <InviteMemberModal onClose={() => setShowInvite(false)} />}
    </>
  )
}
