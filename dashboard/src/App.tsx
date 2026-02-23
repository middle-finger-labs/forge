import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useSession } from './lib/auth.ts'
import PipelineListPage from './pages/PipelineListPage.tsx'
import PipelineDetailPage from './pages/PipelineDetailPage.tsx'
import AdminPage from './pages/AdminPage.tsx'
import SettingsPage from './pages/SettingsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import SignupPage from './pages/SignupPage.tsx'

// ---------------------------------------------------------------------------
// ProtectedRoute — redirects to /login when unauthenticated
// ---------------------------------------------------------------------------

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { data: session, isPending } = useSession()
  const location = useLocation()

  if (isPending) {
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
