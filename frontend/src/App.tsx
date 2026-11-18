import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ComingSoon } from './components/ui'
import { AuthProvider, homeFor, useAuth } from './modules/auth/AuthContext'
import { ChangePasswordPage, ForgotPasswordPage, LoginPage, ResetPasswordPage } from './modules/auth/AuthPages'
import { CustomersPage, DriversPage, EmployeesPage, VehiclesPage, VendorsPage } from './modules/master/MasterPages'
import { CompliancePage } from './modules/compliance/CompliancePage'
import { ExpensesPage } from './modules/expenses/ExpensesPage'
import { DashboardPage } from './modules/dashboard/DashboardPage'
import { ReportsPage } from './modules/reports/ReportsPage'
import { SmsLogsPage } from './modules/notifications/SmsLogsPage'
import { SettingsPage } from './modules/settings/SettingsPage'
import { TripAssignPage } from './modules/trips/TripAssignPage'
import { TripDetailPage } from './modules/trips/TripDetailPage'
import { TripFormPage } from './modules/trips/TripFormPage'
import { TripsPage } from './modules/trips/TripsPage'
import { StatusPage } from './modules/system/StatusPage'
import { UsersPage } from './modules/users/UsersPage'
import { ProtectedLayout, RequireRole } from './routes/Guards'
import { NAV_ITEMS } from './routes/nav'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: false } } })

const PHASES: Record<string, string> = {
  '/expenses': 'a later release', '/dashboard': 'Phase 7', '/trips': 'Phases 4–5', '/reports': 'Phase 7', '/vehicles': 'Phase 3', '/drivers': 'Phase 3',
  '/customers': 'Phase 3', '/employees': 'Phase 3', '/vendors': 'Phase 3', '/compliance': 'Phase 8',
  '/notifications': 'Phase 6', '/settings': 'Phase 8',
}

const IMPLEMENTED: Record<string, ReactElement> = {
  '/dashboard': <DashboardPage />, '/expenses': <ExpensesPage />, '/compliance': <CompliancePage />, '/reports': <ReportsPage />, '/trips': <TripsPage />, '/notifications': <SmsLogsPage />, '/settings': <SettingsPage />,
  '/users': <UsersPage />, '/vendors': <VendorsPage />, '/customers': <CustomersPage />,
  '/employees': <EmployeesPage />, '/drivers': <DriversPage />, '/vehicles': <VehiclesPage />,
}

function Root() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? homeFor(user.role) : '/login'} replace />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/status" element={<StatusPage />} />
            <Route element={<ProtectedLayout />}>
              {NAV_ITEMS.filter((n) => !IMPLEMENTED[n.to]).map((n) => (
                <Route key={n.to} element={<RequireRole roles={n.roles} />}>
                  <Route path={n.to} element={<ComingSoon title={n.label} phase={PHASES[n.to]} />} />
                </Route>
              ))}
              <Route element={<RequireRole roles={['super_admin', 'vendor_admin', 'operator']} />}>
                <Route path="/trips/new" element={<TripFormPage />} />
                <Route path="/trips/:id/edit" element={<TripFormPage />} />
              </Route>
              <Route element={<RequireRole roles={['super_admin', 'vendor_admin']} />}>
                <Route path="/trips/:id/assign" element={<TripAssignPage />} />
              </Route>
              <Route path="/trips/:id" element={<TripDetailPage />} />
              {NAV_ITEMS.filter((n) => IMPLEMENTED[n.to]).map((n) => (
                <Route key={n.to} element={<RequireRole roles={n.roles} />}>
                  <Route path={n.to} element={IMPLEMENTED[n.to]} />
                </Route>
              ))}
            </Route>
            <Route path="*" element={<Root />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
