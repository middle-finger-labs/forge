import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle,
  ChevronDown,
  CircleAlert,
  Eye,
  EyeOff,
  GitBranch,
  Key,
  Loader2,
  Plus,
  Save,
  Settings,
  Shield,
  Star,
  Trash2,
  Users,
  X,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'
import {
  useSession,
  useActiveOrganization,
  organization,
} from '../lib/auth.ts'
import {
  getOrgSettings,
  updateOrgSettings,
  listSecrets,
  setSecret,
  deleteSecret,
  listIdentities,
  createIdentity,
  deleteIdentity,
  testIdentity,
} from '../lib/api.ts'
import type { OrgSettings, OrgSecretKey, OrgIdentity } from '../lib/api.ts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = 'general' | 'api-keys' | 'identities' | 'members'

interface OrgMember {
  id: string
  userId: string
  role: string
  email?: string
  name?: string
  image?: string
  createdAt: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function maskSecret(key: string): string {
  if (key.length <= 8) return '****'
  return key.slice(0, 5) + '...' + key.slice(-4)
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

const ROLE_BADGE: Record<string, string> = {
  owner: 'bg-amber-900/60 text-amber-300 ring-amber-700/40',
  admin: 'bg-blue-900/60 text-blue-300 ring-blue-700/40',
  member: 'bg-slate-700/60 text-slate-300 ring-slate-600/40',
}

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'general', label: 'General', icon: <Settings className="h-4 w-4" /> },
  { key: 'api-keys', label: 'API Keys', icon: <Key className="h-4 w-4" /> },
  { key: 'identities', label: 'GitHub Identities', icon: <GitBranch className="h-4 w-4" /> },
  { key: 'members', label: 'Members', icon: <Users className="h-4 w-4" /> },
]

const ALL_STAGES = [
  'business_analysis',
  'research',
  'architecture',
  'task_decomposition',
]

// ---------------------------------------------------------------------------
// General Tab
// ---------------------------------------------------------------------------

function GeneralTab({ userRole }: { userRole: string }) {
  const [settings, setSettings] = useState<OrgSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: activeOrg } = useActiveOrganization()

  // Editable fields
  const [maxCost, setMaxCost] = useState(50)
  const [maxConcurrent, setMaxConcurrent] = useState(3)
  const [modelTier, setModelTier] = useState('strong')
  const [prStrategy, setPrStrategy] = useState('single_pr')
  const [memorySharingMode, setMemorySharingMode] = useState('shared')
  const [autoApprove, setAutoApprove] = useState<string[]>([])

  useEffect(() => {
    getOrgSettings()
      .then((s) => {
        setSettings(s)
        setMaxCost(s.max_pipeline_cost_usd)
        setMaxConcurrent(s.max_concurrent_pipelines)
        setModelTier(s.default_model_tier)
        setPrStrategy(s.pr_strategy)
        setMemorySharingMode(s.memory_sharing_mode ?? 'shared')
        setAutoApprove(s.auto_approve_stages ?? [])
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  function toggleStage(stage: string) {
    setAutoApprove((prev) =>
      prev.includes(stage) ? prev.filter((s) => s !== stage) : [...prev, stage],
    )
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateOrgSettings({
        max_pipeline_cost_usd: maxCost,
        max_concurrent_pipelines: maxConcurrent,
        default_model_tier: modelTier,
        pr_strategy: prStrategy,
        memory_sharing_mode: memorySharingMode,
        auto_approve_stages: autoApprove,
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const isReadOnly = userRole === 'member'

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading settings...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Organization name */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Organization Name
        </label>
        <input
          type="text"
          value={activeOrg?.name ?? settings?.org_id ?? ''}
          disabled
          className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-slate-400"
        />
        <p className="mt-1 text-xs text-slate-500">Organization name cannot be changed here.</p>
      </div>

      {/* Max pipeline cost */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Max Pipeline Cost per Run
        </label>
        <div className="relative max-w-xs">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-500">$</span>
          <input
            type="number"
            min={1}
            max={500}
            step={1}
            value={maxCost}
            onChange={(e) => setMaxCost(Number(e.target.value))}
            disabled={isReadOnly}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 py-2 pl-7 pr-3 text-sm text-slate-200 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
          />
        </div>
      </div>

      {/* Max concurrent pipelines */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Max Concurrent Pipelines
        </label>
        <input
          type="number"
          min={1}
          max={20}
          value={maxConcurrent}
          onChange={(e) => setMaxConcurrent(Number(e.target.value))}
          disabled={isReadOnly}
          className="max-w-xs w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
        />
      </div>

      {/* Default model tier */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Default Model Tier
        </label>
        <div className="relative max-w-xs">
          <select
            value={modelTier}
            onChange={(e) => setModelTier(e.target.value)}
            disabled={isReadOnly}
            className="w-full appearance-none rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 pr-8 text-sm text-slate-200 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
          >
            <option value="frontier">Frontier</option>
            <option value="strong">Strong</option>
            <option value="local_coder">Local Coder</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
        </div>
      </div>

      {/* PR strategy */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Default PR Strategy
        </label>
        <div className="flex gap-4">
          {(
            [
              ['single_pr', 'Single PR'],
              ['pr_per_ticket', 'PR per Ticket'],
              ['direct_push', 'Direct Push'],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="pr-strategy"
                value={value}
                checked={prStrategy === value}
                onChange={() => setPrStrategy(value)}
                disabled={isReadOnly}
                className="accent-cyan-500"
              />
              {label}
            </label>
          ))}
        </div>
      </div>

      {/* Memory sharing mode */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Memory Sharing Mode
        </label>
        <p className="mb-2 text-xs text-slate-500">
          Controls whether pipeline lessons and decisions are visible to all org members.
        </p>
        <div className="flex gap-4">
          {(
            [
              ['shared', 'Shared', 'All members see all memories'],
              ['private', 'Private', 'Each member only sees their own'],
            ] as const
          ).map(([value, label, desc]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="memory-sharing"
                value={value}
                checked={memorySharingMode === value}
                onChange={() => setMemorySharingMode(value)}
                disabled={isReadOnly}
                className="accent-cyan-500"
              />
              <span>
                {label}
                <span className="ml-1 text-xs text-slate-500">— {desc}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Auto-approve stages */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-300">
          Auto-Approve Stages
        </label>
        <p className="mb-2 text-xs text-slate-500">
          Selected stages will be automatically approved without human review.
        </p>
        <div className="flex flex-wrap gap-3">
          {ALL_STAGES.map((stage) => (
            <label key={stage} className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={autoApprove.includes(stage)}
                onChange={() => toggleStage(stage)}
                disabled={isReadOnly}
                className="rounded border-slate-600 bg-slate-700 accent-cyan-500"
              />
              {stage.replace(/_/g, ' ')}
            </label>
          ))}
        </div>
      </div>

      {/* Save */}
      {!isReadOnly && (
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
          {saved && (
            <span className="flex items-center gap-1 text-sm text-emerald-400">
              <CheckCircle className="h-4 w-4" /> Saved
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// API Keys Tab
// ---------------------------------------------------------------------------

function AddKeyModal({
  onClose,
  onAdded,
}: {
  onClose: () => void
  onAdded: () => void
}) {
  const [keyName, setKeyName] = useState('ANTHROPIC_API_KEY')
  const [customName, setCustomName] = useState('')
  const [value, setValue] = useState('')
  const [showValue, setShowValue] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  const effectiveName = keyName === 'custom' ? customName.trim() : keyName

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!effectiveName || !value.trim()) return
    setLoading(true)
    setError(null)
    try {
      await setSecret(effectiveName, value.trim())
      onAdded()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save key')
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
          <h3 className="text-sm font-semibold text-slate-100">Add API Key</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3 px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Key Name</label>
            <div className="relative">
              <select
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                className="w-full appearance-none rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 pr-8 text-sm text-slate-200 focus:border-cyan-600 focus:outline-none"
              >
                <option value="ANTHROPIC_API_KEY">ANTHROPIC_API_KEY</option>
                <option value="OPENAI_API_KEY">OPENAI_API_KEY</option>
                <option value="custom">Custom...</option>
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            </div>
          </div>
          {keyName === 'custom' && (
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Custom Key Name</label>
              <input
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                required
                placeholder="MY_SECRET_KEY"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Value</label>
            <div className="relative">
              <input
                type={showValue ? 'text' : 'password'}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                required
                placeholder="sk-..."
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 pr-10 font-mono text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowValue((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                {showValue ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={loading || !effectiveName || !value.trim()}
            className="w-full rounded-lg bg-cyan-600 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {loading ? 'Saving...' : 'Save Key'}
          </button>
        </form>
      </div>
    </div>
  )
}

function ApiKeysTab({ userRole }: { userRole: string }) {
  const [keys, setKeys] = useState<OrgSecretKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const isReadOnly = userRole === 'member'

  const loadKeys = useCallback(() => {
    listSecrets()
      .then((r) => setKeys(r.keys))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadKeys()
  }, [loadKeys])

  async function handleDelete(key: string) {
    setDeleting(key)
    try {
      await deleteSecret(key)
      setKeys((prev) => prev.filter((k) => k.key !== key))
      setConfirmDelete(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete')
    } finally {
      setDeleting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading keys...
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          API keys are encrypted at rest and never displayed after storage.
        </p>
        {!isReadOnly && (
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-cyan-500"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Key
          </button>
        )}
      </div>

      {keys.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-12 text-center">
          <Key className="mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-400">No API keys configured</p>
          <p className="text-xs text-slate-500">
            Add your Anthropic or OpenAI API keys to run pipelines.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <div
              key={k.key}
              className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <Key className="h-4 w-4 text-slate-500" />
                <div>
                  <p className="font-mono text-sm text-slate-200">{k.key}</p>
                  <p className="text-xs text-slate-500">
                    Updated {relativeTime(k.updated_at)} by {maskSecret(k.created_by)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1 rounded-full bg-amber-900/40 px-2 py-0.5 text-xs text-amber-300 ring-1 ring-inset ring-amber-700/40">
                  <CircleAlert className="h-3 w-3" />
                  Encrypted
                </span>
                {!isReadOnly && (
                  <>
                    {confirmDelete === k.key ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(k.key)}
                          disabled={deleting === k.key}
                          className="rounded px-2 py-1 text-xs font-medium text-red-400 transition hover:bg-red-900/40"
                        >
                          {deleting === k.key ? 'Deleting...' : 'Confirm'}
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(k.key)}
                        className="rounded p-1.5 text-slate-500 transition hover:bg-red-900/30 hover:text-red-400"
                        title="Delete key"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && <AddKeyModal onClose={() => setShowAdd(false)} onAdded={loadKeys} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// GitHub Identities Tab
// ---------------------------------------------------------------------------

function AddIdentityModal({
  onClose,
  onAdded,
}: {
  onClose: () => void
  onAdded: () => void
}) {
  const [name, setName] = useState('')
  const [ghUser, setGhUser] = useState('')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [sshKey, setSshKey] = useState('')
  const [ghOrg, setGhOrg] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [showToken, setShowToken] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !ghUser.trim() || !email.trim()) return
    setLoading(true)
    setError(null)
    try {
      await createIdentity({
        name: name.trim(),
        github_username: ghUser.trim(),
        email: email.trim(),
        github_token: token.trim() || undefined,
        ssh_key: sshKey.trim() || undefined,
        github_org: ghOrg.trim() || undefined,
        is_default: isDefault,
      })
      onAdded()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create identity')
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
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-100">Add GitHub Identity</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3 px-5 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                autoFocus
                placeholder="default"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">GitHub Username</label>
              <input
                value={ghUser}
                onChange={(e) => setGhUser(e.target.value)}
                required
                placeholder="octocat"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="dev@example.com"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              GitHub Token (PAT)
            </label>
            <div className="relative">
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="ghp_..."
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 pr-10 font-mono text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              SSH Key <span className="text-slate-600">(optional)</span>
            </label>
            <textarea
              value={sshKey}
              onChange={(e) => setSshKey(e.target.value)}
              rows={3}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              className="w-full resize-y rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">
                GitHub Org <span className="text-slate-600">(optional)</span>
              </label>
              <input
                value={ghOrg}
                onChange={(e) => setGhOrg(e.target.value)}
                placeholder="my-org"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
              />
            </div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-700 accent-cyan-500"
                />
                Set as default identity
              </label>
            </div>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={loading || !name.trim() || !ghUser.trim() || !email.trim()}
            className="w-full rounded-lg bg-cyan-600 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            {loading ? 'Creating...' : 'Add Identity'}
          </button>
        </form>
      </div>
    </div>
  )
}

function IdentitiesTab({ userRole }: { userRole: string }) {
  const [identities, setIdentities] = useState<OrgIdentity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>({})
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  const isReadOnly = userRole === 'member'

  const loadIdentities = useCallback(() => {
    listIdentities()
      .then(setIdentities)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadIdentities()
  }, [loadIdentities])

  async function handleTest(id: string) {
    setTesting(id)
    try {
      const res = await testIdentity(id)
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: res.status === 'ok', detail: res.detail },
      }))
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: false, detail: err instanceof Error ? err.message : 'Test failed' },
      }))
    } finally {
      setTesting(null)
    }
  }

  async function handleDelete(id: string) {
    setDeleting(id)
    try {
      await deleteIdentity(id)
      setIdentities((prev) => prev.filter((i) => i.id !== id))
      setConfirmDelete(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete')
    } finally {
      setDeleting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading identities...
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          GitHub identities used for committing code and pushing PRs.
        </p>
        {!isReadOnly && (
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-cyan-500"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Identity
          </button>
        )}
      </div>

      {identities.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-12 text-center">
          <GitBranch className="mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-400">No GitHub identities configured</p>
          <p className="text-xs text-slate-500">
            Add an identity to push code and create PRs.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {identities.map((ident) => {
            const tr = testResults[ident.id]
            return (
              <div
                key={ident.id}
                className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <GitBranch className="mt-0.5 h-4 w-4 text-slate-500" />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-slate-200">{ident.name}</p>
                        {ident.is_default && (
                          <span className="flex items-center gap-1 rounded-full bg-cyan-900/40 px-2 py-0.5 text-xs text-cyan-300 ring-1 ring-inset ring-cyan-700/40">
                            <Star className="h-3 w-3" />
                            Default
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400">
                        @{ident.github_username} &middot; {ident.email}
                        {ident.github_org && (
                          <> &middot; org: {ident.github_org}</>
                        )}
                      </p>
                      {tr && (
                        <p
                          className={clsx(
                            'mt-1 text-xs',
                            tr.ok ? 'text-emerald-400' : 'text-red-400',
                          )}
                        >
                          {tr.ok ? <><CheckCircle className="mr-1 inline h-3 w-3" />Connected</> : tr.detail}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleTest(ident.id)}
                      disabled={testing === ident.id}
                      className="rounded px-2.5 py-1 text-xs font-medium text-slate-400 transition hover:bg-slate-700 hover:text-slate-200 disabled:opacity-50"
                    >
                      {testing === ident.id ? (
                        <Loader2 className="inline h-3 w-3 animate-spin" />
                      ) : (
                        'Test'
                      )}
                    </button>
                    {!isReadOnly && (
                      <>
                        {confirmDelete === ident.id ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDelete(ident.id)}
                              disabled={deleting === ident.id}
                              className="rounded px-2 py-1 text-xs font-medium text-red-400 hover:bg-red-900/40"
                            >
                              {deleting === ident.id ? '...' : 'Confirm'}
                            </button>
                            <button
                              onClick={() => setConfirmDelete(null)}
                              className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDelete(ident.id)}
                            className="rounded p-1.5 text-slate-500 transition hover:bg-red-900/30 hover:text-red-400"
                            title="Delete identity"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showAdd && <AddIdentityModal onClose={() => setShowAdd(false)} onAdded={loadIdentities} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Members Tab
// ---------------------------------------------------------------------------

function InviteModal({ onClose, onInvited }: { onClose: () => void; onInvited: () => void }) {
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
        onInvited()
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
              placeholder="colleague@example.com"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-cyan-600 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">Role</label>
            <div className="flex gap-4">
              {(['member', 'admin'] as const).map((r) => (
                <label key={r} className="flex items-center gap-2 text-sm text-slate-300">
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

function MembersTab({ userRole }: { userRole: string }) {
  const { data: activeOrg } = useActiveOrganization()
  const { data: session } = useSession()
  const [showInvite, setShowInvite] = useState(false)
  const [changingRole, setChangingRole] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isOwner = userRole === 'owner'
  const isAdmin = userRole === 'owner' || userRole === 'admin'

  // Extract members from the active org data
  const members: OrgMember[] = (activeOrg?.members ?? []).map(
    (m: Record<string, unknown>) => ({
      id: String(m.id ?? ''),
      userId: String(m.userId ?? ''),
      role: String(m.role ?? 'member'),
      email: m.email != null ? String(m.email) : undefined,
      name: m.name != null ? String(m.name) : undefined,
      image: m.image != null ? String(m.image) : undefined,
      createdAt: String(m.createdAt ?? ''),
    }),
  )

  async function handleRoleChange(memberId: string, newRole: string) {
    setChangingRole(memberId)
    setError(null)
    try {
      await organization.updateMemberRole({
        memberId,
        role: newRole as 'admin' | 'member',
      })
      // Refresh page to reflect changes
      window.location.reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change role')
    } finally {
      setChangingRole(null)
    }
  }

  async function handleRemove(memberId: string) {
    setRemoving(memberId)
    setError(null)
    try {
      await organization.removeMember({ memberIdOrEmail: memberId })
      window.location.reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove member')
    } finally {
      setRemoving(null)
      setConfirmRemove(null)
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          {members.length} member{members.length !== 1 ? 's' : ''} in this organization
        </p>
        {isAdmin && (
          <button
            onClick={() => setShowInvite(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-cyan-500"
          >
            <Plus className="h-3.5 w-3.5" />
            Invite Member
          </button>
        )}
      </div>

      {members.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-700 py-12 text-center">
          <Users className="mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-400">No members found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {members.map((m) => {
            const isSelf = m.userId === session?.user?.id
            const initials = (m.name ?? m.email ?? '?')
              .split(' ')
              .map((w: string) => w[0])
              .join('')
              .toUpperCase()
              .slice(0, 2)

            return (
              <div
                key={m.id}
                className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  {m.image ? (
                    <img
                      src={m.image}
                      alt=""
                      className="h-8 w-8 rounded-full object-cover"
                    />
                  ) : (
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-300">
                      {initials}
                    </div>
                  )}
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-200">
                        {m.name ?? 'Unnamed'}
                        {isSelf && (
                          <span className="ml-1.5 text-xs text-slate-500">(you)</span>
                        )}
                      </p>
                      <span
                        className={clsx(
                          'inline-block rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
                          ROLE_BADGE[m.role] ?? ROLE_BADGE.member,
                        )}
                      >
                        {m.role}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500">
                      {m.email}
                      {m.createdAt && (
                        <> &middot; Joined {relativeTime(m.createdAt)}</>
                      )}
                    </p>
                  </div>
                </div>

                {/* Actions */}
                {isOwner && !isSelf && m.role !== 'owner' && (
                  <div className="flex items-center gap-2">
                    {/* Role change */}
                    <div className="relative">
                      <select
                        value={m.role}
                        onChange={(e) => handleRoleChange(m.id, e.target.value)}
                        disabled={changingRole === m.id}
                        className="appearance-none rounded-lg border border-slate-600 bg-slate-700 px-2 py-1 pr-6 text-xs text-slate-300 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                      <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
                    </div>

                    {/* Remove */}
                    {confirmRemove === m.id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleRemove(m.id)}
                          disabled={removing === m.id}
                          className="rounded px-2 py-1 text-xs font-medium text-red-400 hover:bg-red-900/40"
                        >
                          {removing === m.id ? '...' : 'Remove'}
                        </button>
                        <button
                          onClick={() => setConfirmRemove(null)}
                          className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmRemove(m.id)}
                        className="rounded p-1.5 text-slate-500 transition hover:bg-red-900/30 hover:text-red-400"
                        title="Remove member"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onInvited={() => {
            // Org data refreshes automatically via better-auth
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings Page (main)
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('general')
  const { data: activeOrg } = useActiveOrganization()
  const { data: session } = useSession()

  // Determine user role in the active org
  const currentUserId = session?.user?.id
  const userRole =
    (activeOrg?.members as Record<string, unknown>[] | undefined)?.find(
      (m) => m.userId === currentUserId,
    )?.role as string ?? 'member'

  // Restrict Members tab changes to admin/owner, API Keys and Identities to admin/owner
  const restrictedTabs: Tab[] =
    userRole === 'member' ? [] : [] // All tabs visible; write restrictions handled per-tab

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-6 py-4">
          <Link
            to="/"
            className="text-slate-400 transition hover:text-slate-200"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-cyan-400" />
            <h1 className="text-lg font-bold tracking-tight text-slate-100">Settings</h1>
          </div>
          {activeOrg?.name && (
            <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs text-slate-400">
              {activeOrg.name}
            </span>
          )}
          <div className="flex-1" />
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset',
              ROLE_BADGE[userRole] ?? ROLE_BADGE.member,
            )}
          >
            <Shield className="h-3 w-3" />
            {userRole}
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-6">
        {/* Tab bar */}
        <nav className="mb-6 flex gap-1 rounded-lg border border-slate-800 bg-slate-900/50 p-1">
          {TABS.filter((t) => !restrictedTabs.includes(t.key)).map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={clsx(
                'flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition',
                activeTab === t.key
                  ? 'bg-slate-800 text-slate-100 shadow-sm'
                  : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-300',
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </nav>

        {/* Tab content */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-6">
          {activeTab === 'general' && <GeneralTab userRole={userRole} />}
          {activeTab === 'api-keys' && <ApiKeysTab userRole={userRole} />}
          {activeTab === 'identities' && <IdentitiesTab userRole={userRole} />}
          {activeTab === 'members' && <MembersTab userRole={userRole} />}
        </div>
      </div>
    </div>
  )
}
