import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useSession, useActiveOrganization, useListOrganizations, organization } from './lib/auth.ts'
import PipelineListPage from './pages/PipelineListPage.tsx'
import PipelineDetailPage from './pages/PipelineDetailPage.tsx'
import AdminPage from './pages/AdminPage.tsx'
import SettingsPage from './pages/SettingsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import SignupPage from './pages/SignupPage.tsx'

// ---------------------------------------------------------------------------
// ProtectedRoute — redirects to /login when unauthenticated,
// auto-selects org when none is active
// ---------------------------------------------------------------------------

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { data: session, isPending } = useSession()
  const { data: activeOrg, isPending: orgPending } = useActiveOrganization()
  const { data: orgList } = useListOrganizations()
  const location = useLocation()
  const [settingOrg, setSettingOrg] = useState(false)

  // Auto-select the first org if the user has orgs but none is active
  useEffect(() => {
    if (
      session &&
      !orgPending &&
      !activeOrg &&
      orgList &&
      orgList.length > 0 &&
      !settingOrg
    ) {
      setSettingOrg(true)
      organization
        .setActive({ organizationId: orgList[0].id })
        .then(() => window.location.reload())
        .catch(() => setSettingOrg(false))
    }
  }, [session, activeOrg, orgPending, orgList, settingOrg])

  if (isPending || settingOrg) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-500">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-cyan-400" />
      </div>
    )
  }

  if (!session) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      {/* Protected routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <PipelineListPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/pipeline/:id"
        element={
          <ProtectedRoute>
            <PipelineDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <AdminPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <SettingsPage />
          </ProtectedRoute>
        }
      />

      {/* Catch-all redirect */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
