import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AppLayout } from '../components/AppLayout'
import { homeFor, useAuth } from '../modules/auth/AuthContext'
import type { Role } from '../types'

/** UX only – the API enforces real authorization. */
export function ProtectedLayout() {
  const { user, loading, logout } = useAuth()
  const loc = useLocation()
  if (loading) return <div style={{ padding: 40 }} className="muted">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (user.must_change_password) return <Navigate to="/change-password" replace />
  return <AppLayout user={user} onLogout={logout} />
}

export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth()
  if (user && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />
  return <Outlet />
}
