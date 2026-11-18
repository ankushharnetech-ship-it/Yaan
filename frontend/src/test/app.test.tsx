import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../modules/auth/AuthContext'
import { LoginPage } from '../modules/auth/AuthPages'
import { StateBadge } from '../modules/compliance/CompliancePage'
import { ChartCard } from '../modules/dashboard/charts'
import { CancelTripModal } from '../modules/trips/shared'
import { Modal } from '../components/ui'
import { CustomersPage, EmployeesPage, VehiclesPage, VendorsPage } from '../modules/master/MasterPages'
import { SmsLogsPage } from '../modules/notifications/SmsLogsPage'
import { SettingsPage } from '../modules/settings/SettingsPage'
import { DriverTripsPage } from '../modules/trips/DriverTripsPage'
import { TripDetailPage } from '../modules/trips/TripDetailPage'
import { TripFormPage } from '../modules/trips/TripFormPage'
import { TripsPage } from '../modules/trips/TripsPage'
import { ExpensesPage } from '../modules/expenses/ExpensesPage'
import { UsersPage } from '../modules/users/UsersPage'
import { ProtectedLayout, RequireRole } from '../routes/Guards'
import { navFor } from '../routes/nav'
import { ApiError, api, tokenStore } from '../services/api'
import type { Role } from '../types'

type Handler = (url: string, init?: RequestInit) => { status?: number; body: unknown }
function mockFetch(routes: Record<string, Handler | unknown>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const key = Object.keys(routes).find((k) => url.startsWith(k))
    if (!key) return new Response(JSON.stringify({ detail: `unmocked ${url}` }), { status: 500 })
    const r = routes[key]
    const out = typeof r === 'function' ? (r as Handler)(url, init) : { body: r }
    return new Response(JSON.stringify(out.body), { status: out.status ?? 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
const me = (role: Role, extra: object = {}) => ({ id: 1, username: 'u', first_name: 'Test', last_name: 'User', email: 'u@example.com', role, vendor_id: role === 'super_admin' ? null : 1, must_change_password: false, ...extra })
const wrap = (ui: ReactNode, path = '/') => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthProvider><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></AuthProvider>
  </QueryClientProvider>
)

describe('role-based navigation (spec §4)', () => {
  const labels = (r: Role) => navFor(r).map((n) => n.label)
  it('drivers get their trips, expenses, compliance and SMS', () => expect(labels('driver')).toEqual(['Trips', 'Expenses', 'Compliance', 'Notifications']))
  it('operators get operations and employees, but no drivers, vehicles, vendors, users or settings', () => {
    expect(labels('operator')).toEqual(['Dashboard', 'Trips', 'Expenses', 'Reports', 'Employees', 'Compliance', 'Notifications'])
  })
  it('vendor admins manage master data and users but never see Vendors', () => {
    const l = labels('vendor_admin')
    expect(l).toEqual(expect.arrayContaining(['Dashboard', 'Drivers', 'Vehicles', 'Customers', 'Employees', 'Users', 'Settings']))
    expect(l).not.toContain('Vendors')
  })
  it('only the super admin sees Vendors', () => {
    expect(labels('super_admin')).toContain('Vendors')
    expect(['driver', 'operator', 'vendor_admin'].some((r) => labels(r as Role).includes('Vendors'))).toBe(false)
  })
  it('drivers never get the dashboard', () => expect(labels('driver')).not.toContain('Dashboard'))
})

describe('api client', () => {
  it('maps validation errors onto field names', async () => {
    mockFetch({ '/api/x': () => ({ status: 422, body: { detail: [{ loc: ['body', 'email'], msg: 'Email is already in use' }] } }) })
    const err = await api('/x').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).fieldErrors).toEqual({ email: 'Email is already in use' })
  })
  it('sends the bearer token', async () => {
    tokenStore.set('abc')
    const f = mockFetch({ '/api/ping': { ok: true } })
    await api('/ping')
    expect((f.mock.calls[0][1]!.headers as Record<string, string>).Authorization).toBe('Bearer abc')
  })
})

describe('login', () => {
  it('shows the server error and keeps the user on the form', async () => {
    mockFetch({ '/api/auth/login': () => ({ status: 401, body: { detail: 'Invalid username or password' } }) })
    render(wrap(<LoginPage />))
    await userEvent.type(screen.getByLabelText('Username'), 'bob')
    await userEvent.type(screen.getByLabelText('Password'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password')
    expect(tokenStore.get()).toBeNull()
  })
  it('stores the session and sends a driver to Trips', async () => {
    mockFetch({ '/api/auth/login': { access_token: 't0k', user: me('driver') } })
    render(wrap(<Routes><Route path="/" element={<LoginPage />} /><Route path="/trips" element={<p>Trips screen</p>} /><Route path="/dashboard" element={<p>Dashboard screen</p>} /></Routes>))
    await userEvent.type(screen.getByLabelText('Username'), 'drv')
    await userEvent.type(screen.getByLabelText('Password'), 'Secret#12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Trips screen')).toBeInTheDocument()
    expect(tokenStore.get()).toBe('t0k')
  })
  it('forces a temporary-password user to change it first', async () => {
    mockFetch({ '/api/auth/login': { access_token: 't', user: me('operator', { must_change_password: true }) } })
    render(wrap(<Routes><Route path="/" element={<LoginPage />} /><Route path="/change-password" element={<p>Choose a new password</p>} /></Routes>))
    await userEvent.type(screen.getByLabelText('Username'), 'op')
    await userEvent.type(screen.getByLabelText('Password'), 'Temp#123456')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Choose a new password')).toBeInTheDocument()
  })
})

describe('route guards (UX layer - the API enforces the real rules)', () => {
  const tree = (
    <Routes>
      <Route path="/login" element={<p>Login screen</p>} />
      <Route path="/change-password" element={<p>Change password screen</p>} />
      <Route element={<ProtectedLayout />}>
        <Route element={<RequireRole roles={['super_admin', 'vendor_admin', 'operator']} />}><Route path="/dashboard" element={<p>Dashboard screen</p>} /></Route>
        <Route path="/trips" element={<p>Trips screen</p>} />
      </Route>
    </Routes>
  )
  it('sends anonymous visitors to login', async () => {
    render(wrap(tree, '/dashboard'))
    expect(await screen.findByText('Login screen')).toBeInTheDocument()
  })
  it('bounces a driver away from the dashboard', async () => {
    tokenStore.set('t'); mockFetch({ '/api/auth/me': me('driver') })
    render(wrap(tree, '/dashboard'))
    expect(await screen.findByText('Trips screen')).toBeInTheDocument()
    expect(screen.queryByText('Dashboard screen')).not.toBeInTheDocument()
  })
  it('lets an operator in', async () => {
    tokenStore.set('t'); mockFetch({ '/api/auth/me': me('operator') })
    render(wrap(tree, '/dashboard'))
    expect(await screen.findByText('Dashboard screen')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Vendors' })).not.toBeInTheDocument()
  })
  it('holds users with a temporary password on the change-password page', async () => {
    tokenStore.set('t'); mockFetch({ '/api/auth/me': me('operator', { must_change_password: true }) })
    render(wrap(tree, '/trips'))
    expect(await screen.findByText('Change password screen')).toBeInTheDocument()
  })
})

describe('user onboarding form', () => {
  it('asks a Super Admin to link a driver record only for the Driver role', async () => {
    tokenStore.set('t')
    mockFetch({
      '/api/auth/me': me('super_admin'),
      '/api/users': { total: 0, items: [] },
      '/api/vendors': { items: [{ id: 1, name: 'Alpha', code: 'A' }] },
      '/api/drivers': { items: [{ id: 9, code: 'DRV-00009', first_name: 'Dev', last_name: 'Driver' }] },
    })
    render(wrap(<UsersPage />))
    await userEvent.click(await screen.findByRole('button', { name: /add user/i }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('A temporary password is generated automatically')
    expect(screen.queryByLabelText(/driver record/i)).not.toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'driver')
    await userEvent.selectOptions(screen.getByLabelText(/^Vendor/), '1')
    expect(await screen.findByLabelText(/driver record/i)).toBeInTheDocument()
    expect(await screen.findByRole('option', { name: /DRV-00009/ })).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument() // admins never type a password
  })
})

describe('expenses (available to every role)', () => {
  // In the app the route guard only renders pages once the user is loaded; mirror that here.
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)
  const OPTS = { categories: [{ id: 1, label: 'Fuel' }], payment_methods: [{ value: 'cash', label: 'Cash' }], vehicles: [{ id: 5, label: 'MH12AB0001 (Dzire)' }], drivers: [{ id: 3, label: 'Dev Driver' }], own_driver_id: 3 }
  const LIST = { total: 0, total_amount: 0, items: [] }
  const SUMMARY = { range_label: 'Oct 2026', total: 12500, count: 3, average: 4166.67, previous_total: 10000, change_pct: 25, voided_count: 0, by_category: [], by_vehicle: [], by_payment: [], by_person: [], by_vendor: [], trend: [], trend_unit: 'day', without_vehicle: 0 }

  it('a driver sees only their own list: no summary tab, and is told it is recorded against them', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('driver'), '/api/expenses/options': OPTS, '/api/expenses/summary': { status: 403, body: {} }, '/api/expenses': LIST })
    render(wrap(<Signed><ExpensesPage /></Signed>))
    expect(await screen.findByRole('heading', { name: 'My expenses' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Summary' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /export excel/i })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /add expense/i }))
    expect(await screen.findByText(/recorded against you/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Driver')).not.toBeInTheDocument()
  })
  it('a vendor admin gets the summary with Indian-rupee totals and can export', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/expenses/options': OPTS, '/api/expenses/summary': SUMMARY, '/api/expenses': LIST })
    render(wrap(<Signed><ExpensesPage /></Signed>))
    expect(await screen.findByRole('heading', { name: 'Expenses' })).toBeInTheDocument()
    expect(await screen.findByText('₹12,500.00')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Summary' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /export excel/i })).toBeEnabled()
    expect(screen.queryByLabelText('Vendor')).not.toBeInTheDocument() // only the Super Admin chooses a vendor
  })
  it('only the Super Admin gets a vendor filter', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('super_admin'), '/api/vendors': { items: [{ id: 1, name: 'Alpha' }] }, '/api/expenses/options': OPTS, '/api/expenses/summary': SUMMARY, '/api/expenses': LIST })
    render(wrap(<Signed><ExpensesPage /></Signed>))
    expect(await screen.findByLabelText('Vendor')).toBeInTheDocument()
  })
})

describe('trips table drawer and field labels', () => {
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)
  const trip = {
    id: 1, code: 'TRP-000001', status: 'assigned', customer_name: 'Acme', site_name: 'HQ', passenger_count: 2, escort_required: false,
    scheduled_start: '2030-01-07T09:00:00+00:00', scheduled_end: '2030-01-07T10:00:00+00:00', driver_name: 'Ravi K', vehicle_number: 'MH12AB1234',
    sms_status: 'sent', created_by: 'Op One', pickup_address: '12 MG Road, Pune', drop_address: 'Acme HQ, Hinjewadi',
    can_assign: true, can_edit: true, can_cancel: true, passengers: [],
  }
  it('always shows pickup and drop under every trip, with nothing to click', async () => {
    tokenStore.set('t')
    const second = { ...trip, id: 2, code: 'TRP-000002', pickup_address: '5 Lotus Lane, Baner', drop_address: 'Acme Annex, Kharadi' }
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/trips': { total: 2, items: [trip, second] }, '/api/customers': { items: [] }, '/api/drivers': { items: [] }, '/api/vehicles': { items: [] } })
    render(wrap(<Signed><TripsPage /></Signed>))
    expect(await screen.findByText('12 MG Road, Pune')).toBeInTheDocument()          // visible straight away
    expect(screen.getByText('Acme HQ, Hinjewadi')).toBeInTheDocument()
    expect(screen.getByText('5 Lotus Lane, Baner')).toBeInTheDocument()              // for every row, not just the first
    expect(screen.getByText('Acme Annex, Kharadi')).toBeInTheDocument()
    expect(screen.getByLabelText('Pickup and drop for TRP-000002')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /show pickup and drop|hide pickup and drop/i })).not.toBeInTheDocument()
  })
  it('the trip form calls the times Start Trip and End Trip', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/lookups': { trip_type: [] }, '/api/customers': { items: [] } })
    render(wrap(<Signed><TripFormPage /></Signed>))
    expect(await screen.findByLabelText(/^Start Trip/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^End Trip/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Start \*/)).not.toBeInTheDocument()
  })
  it('a new trip cannot be booked in the past: the start picker starts at now and the end cannot precede the start', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/lookups': { trip_type: [] }, '/api/customers': { items: [] } })
    render(wrap(<Signed><TripFormPage /></Signed>))
    const start = (await screen.findByLabelText(/^Start Trip/)) as HTMLInputElement
    const end = screen.getByLabelText(/^End Trip/) as HTMLInputElement
    expect(start.min).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
    expect(new Date(start.min).getTime()).toBeLessThanOrEqual(Date.now())
    expect(Date.now() - new Date(start.min).getTime()).toBeLessThan(2 * 60_000) // "now", not some old fixed date
    expect(end.min).toBe(start.min)
    await userEvent.type(start, '2031-06-15T09:30')
    expect(end.min).toBe('2031-06-15T09:30')
    expect(screen.queryByText(/cannot be in the past/i)).not.toBeInTheDocument()
  })
  it('typing a past date shows the error under the field straight away, and a past end time is rejected too', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/lookups': { trip_type: [] }, '/api/customers': { items: [] } })
    render(wrap(<Signed><TripFormPage /></Signed>))
    const start = (await screen.findByLabelText(/^Start Trip/)) as HTMLInputElement
    await userEvent.type(start, '2020-01-01T09:00')
    expect(await screen.findByText('Start time cannot be in the past')).toBeInTheDocument()
    expect(start).toHaveAttribute('aria-invalid', 'true')
    await userEvent.clear(start)
    await userEvent.type(start, '2031-06-15T09:30')
    await waitFor(() => expect(screen.queryByText('Start time cannot be in the past')).not.toBeInTheDocument())
    await userEvent.type(screen.getByLabelText(/^End Trip/), '2031-06-15T09:00')
    expect(await screen.findByText('End time must be after the start time')).toBeInTheDocument()
  })
  it('the employee form has latitude and longitude', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add employee/i }))
    expect(await screen.findByLabelText(/^Latitude/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Longitude/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Latitude/)).toHaveAttribute('type', 'number')
  })
  it('employee address, latitude and longitude are required', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add employee/i }))
    for (const name of [/^Address/, /^Latitude/, /^Longitude/]) expect(await screen.findByLabelText(name)).toBeRequired()
  })
  it('customer address, latitude and longitude are required', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/customers': { total: 0, items: [] } })
    render(wrap(<Signed><CustomersPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add customer/i }))
    for (const name of [/^Address/, /^Latitude/, /^Longitude/]) expect(await screen.findByLabelText(name)).toBeRequired()
  })
  it('turns the validator wording into plain language', async () => {
    mockFetch({ '/api/x': () => ({ status: 422, body: { detail: [
      { type: 'string_type', loc: ['body', 'address'], msg: 'Input should be a valid string', input: null },
      { type: 'float_type', loc: ['body', 'latitude'], msg: 'Input should be a valid number', input: null },
      { type: 'float_parsing', loc: ['body', 'longitude'], msg: 'Input should be a valid number, unable to parse string as a number', input: 'abc' },
      { type: 'less_than_equal', loc: ['body', 'other'], msg: 'Input should be less than or equal to 90', input: 91 },
      { loc: ['body', 'email'], msg: 'Email is already in use' },
    ] } }) })
    const err = await api('/x').catch((e) => e)
    expect((err as ApiError).fieldErrors).toEqual({
      address: 'This field is required', latitude: 'This field is required', longitude: 'Enter a valid number',
      other: 'Input should be less than or equal to 90', email: 'Email is already in use',
    })
  })
})

describe('trip request workflow', () => {
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)
  const base = {
    '/api/lookups': { trip_type: [{ id: 1, code: 'pickup', label: 'Pickup' }] },
    '/api/customers': { items: [{ id: 1, vendor_id: 1, name: 'Acme' }] },
    '/api/sites': { items: [] }, '/api/shifts': { items: [] }, '/api/employees': { items: [] },
  }
  it('an Operator sends a request: no driver or vehicle, and is told what happens next', async () => {
    tokenStore.set('t'); mockFetch({ '/api/auth/me': me('operator'), ...base })
    render(wrap(<Signed><TripFormPage /></Signed>))
    expect(await screen.findByRole('heading', { name: 'Request a trip' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send request' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Driver & vehicle' })).not.toBeInTheDocument()
    expect(screen.queryByText(/SMS preview/i)).not.toBeInTheDocument()
    expect(screen.getByText(/What happens next/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Vendor Admin/).length).toBeGreaterThanOrEqual(1)
  })
  it('a Vendor Admin can also create and assign in one step', async () => {
    tokenStore.set('t'); mockFetch({ '/api/auth/me': me('vendor_admin'), ...base })
    render(wrap(<Signed><TripFormPage /></Signed>))
    expect(await screen.findByRole('heading', { name: 'Create & assign trip' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Driver & vehicle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create & assign trip' })).toBeDisabled() // needs employees, driver and vehicle
  })
  it('a Vendor Admin onboards only Operators and Drivers, always in their own vendor', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/users': { total: 0, items: [] }, '/api/drivers': { items: [] } })
    render(wrap(<Signed><UsersPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add user/i }))
    const role = await screen.findByLabelText(/^Role/)
    const options = Array.from(role.querySelectorAll('option')).map((o) => o.textContent)
    expect(options).toEqual(['Select role', 'Operator', 'Driver'])   // no Vendor Admin
    expect(screen.queryByLabelText(/^Vendor/)).not.toBeInTheDocument() // no choice of vendor
  })
  it('every manager can edit a user, but only the Super Admin sees Delete', async () => {
    const row = { id: 7, first_name: 'Olive', middle_name: null, last_name: 'Ops', username: 'olive', email: 'o@example.com', mobile: null, gender: null, address: '1 Road',
      role: 'operator', vendor_id: 1, vendor_name: 'Alpha', customer_id: 1, customer_name: 'Acme', status: 'active', credential_status: 'set', last_login_at: null, created_at: '2030-01-01T00:00:00Z' }
    const list = { '/api/users': { total: 1, items: [row] }, '/api/drivers': { items: [] } }
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), ...list })
    const first = render(wrap(<Signed><UsersPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: 'Edit olive' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('cannot be changed')
    expect(screen.queryByRole('button', { name: 'Delete olive' })).not.toBeInTheDocument()
    first.unmount()

    mockFetch({ '/api/auth/me': me('super_admin'), ...list })
    render(wrap(<Signed><UsersPage /></Signed>))
    expect(await screen.findByRole('button', { name: 'Delete olive' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit olive' })).toBeInTheDocument()
  })
  it('an Operator cannot open the users screen links or assignment screen via the menu', () => {
    const labels = navFor('operator').map((n) => n.label)
    expect(labels).not.toContain('Users')
    expect(labels).toContain('Employees')
  })
})

describe('drop-off OTPs', () => {
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)
  const pax = (id: number, name: string, extra: object = {}) => ({
    employee_id: id, sequence: id, name, mobile: '9876543210', gender: 'male', address: 'Somewhere', drop_status: 'pending',
    otp_locked: false, otp_verified_at: null, not_dropped_at: null, not_dropped_reason: null, ...extra,
  })
  const trip = (status: string, passengers: object[], extra: object = {}) => ({
    id: 1, code: 'TRP-000001', status, customer_name: 'Acme', site_name: 'HQ', trip_type: 'Pickup', shift_name: null, route_name: null,
    scheduled_start: '2030-01-07T09:00:00+00:00', scheduled_end: '2030-01-07T10:00:00+00:00', pickup_address: 'A', drop_address: 'B',
    special_instructions: null, created_by: 'Op One', created_by_id: 7, driver_name: 'Ravi K', driver_contact: '9000000001', vehicle_number: 'MH12AB1234',
    vehicle_capacity: 4, required_capacity: 2, passenger_count: passengers.length, escort_required: false, passengers, drops_resolved: 0,
    can_assign: false, can_edit: false, can_cancel: false, history: [], cancelled_at: null, cancelled_by: null, cancellation_reason: null, ...extra,
  })

  it('shows the Operator who requested the trip each employee OTP beside their name', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/trips/1': trip('assigned', [pax(1, 'Asha Rao', { otp: '4821' }), pax(2, 'Ben Roy', { otp: '1907' })]), '/api/sms-logs': { items: [] }, '/api/email-logs': { items: [] } })
    render(wrap(<Signed><Routes><Route path="/trips/:id" element={<TripDetailPage />} /></Routes></Signed>, '/trips/1'))
    expect(await screen.findByLabelText('OTP for Asha Rao')).toHaveTextContent('4821')
    expect(screen.getByLabelText('OTP for Ben Roy')).toHaveTextContent('1907')
    expect(screen.getByText(/never tell the driver/i)).toBeInTheDocument()
  })
  it('shows nobody else an OTP, only whether each employee has been dropped', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/trips/1': trip('started', [pax(1, 'Asha Rao', { drop_status: 'verified' }), pax(2, 'Ben Roy'), pax(3, 'Cy Das', { drop_status: 'not_dropped', not_dropped_reason: 'Did not turn up' })], { drops_resolved: 2 }), '/api/sms-logs': { items: [] }, '/api/email-logs': { items: [] } })
    render(wrap(<Signed><Routes><Route path="/trips/:id" element={<TripDetailPage />} /></Routes></Signed>, '/trips/1'))
    expect(await screen.findByText('Dropped · OTP verified')).toBeInTheDocument()
    expect(screen.getByText('Not dropped')).toBeInTheDocument()
    expect(screen.getByText(/Reason: Did not turn up/)).toBeInTheDocument()
    expect(screen.getByText('2 of 3 dropped')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^OTP for/)).not.toBeInTheDocument()
  })

  const started = (resolved: object[]) => trip('started', resolved, { drops_resolved: resolved.filter((p) => (p as { drop_status: string }).drop_status !== 'pending').length })
  it('the driver cannot end the trip until everyone is dropped', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('driver'), '/api/trips': { total: 1, items: [started([pax(1, 'Asha Rao'), pax(2, 'Ben Roy', { drop_status: 'verified' })])] } })
    render(wrap(<Signed><DriverTripsPage /></Signed>))
    const end = await screen.findByRole('button', { name: /end trip/i })
    expect(end).toBeDisabled()
    expect(screen.getByText(/once 1 more employee is dropped/i)).toBeInTheDocument()
    expect(screen.getByLabelText('OTP from Asha Rao')).toBeInTheDocument()
    expect(screen.queryByLabelText('OTP from Ben Roy')).not.toBeInTheDocument() // already dropped
    expect(screen.getByRole('progressbar', { name: /drop-off progress/i })).toHaveAttribute('aria-valuenow', '50')
  })
  it('the driver can end the trip once every employee is resolved', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('driver'), '/api/trips': { total: 1, items: [started([pax(1, 'Asha Rao', { drop_status: 'verified' }), pax(2, 'Ben Roy', { drop_status: 'not_dropped', not_dropped_reason: 'No show' })])] } })
    render(wrap(<Signed><DriverTripsPage /></Signed>))
    expect(await screen.findByRole('button', { name: /end trip/i })).toBeEnabled()
  })
  it('a wrong OTP shows how many tries are left, and the box is cleared', async () => {
    tokenStore.set('t')
    mockFetch({
      '/api/auth/me': me('driver'),
      '/api/trips/1/passengers/1/verify-otp': () => ({ status: 422, body: { detail: [{ loc: ['body', 'otp'], msg: 'That OTP is not correct. 4 tries left.', code: 'otp_wrong' }] } }),
      '/api/trips': { total: 1, items: [started([pax(1, 'Asha Rao')])] },
    })
    render(wrap(<Signed><DriverTripsPage /></Signed>))
    const input = await screen.findByLabelText('OTP from Asha Rao')
    await userEvent.type(input, '0000')
    await userEvent.click(screen.getByRole('button', { name: /verify/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That OTP is not correct. 4 tries left.')
    expect(input).toHaveValue('')
  })
  it('only digits are accepted in the OTP box', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('driver'), '/api/trips': { total: 1, items: [started([pax(1, 'Asha Rao')])] } })
    render(wrap(<Signed><DriverTripsPage /></Signed>))
    const input = await screen.findByLabelText('OTP from Asha Rao')
    await userEvent.type(input, '4a8-2 1')
    expect(input).toHaveValue('4821')
  })
  it('a locked employee has no OTP box, only the way out', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('driver'), '/api/trips': { total: 1, items: [started([pax(1, 'Asha Rao', { otp_locked: true })])] } })
    render(wrap(<Signed><DriverTripsPage /></Signed>))
    expect(await screen.findByText('OTP locked')).toBeInTheDocument()
    expect(screen.queryByLabelText('OTP from Asha Rao')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /employee not dropped/i }))
    const confirm = screen.getByRole('button', { name: /confirm not dropped/i })
    expect(confirm).toBeDisabled()                                    // a reason is required
    await userEvent.type(screen.getByLabelText(/why was asha rao not dropped/i), 'Phone lost')
    expect(confirm).toBeEnabled()
  })
})

describe('notification settings and mandatory fields', () => {
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)

  it('lets an admin switch SMS and Email independently and says who is notified how', async () => {
    tokenStore.set('t')
    let values = { notify_sms_enabled: true, notify_email_enabled: false, sms_on_cancellation: true, sms_on_reassignment: false, compliance_expiry_warning_days: 30 }
    const f = mockFetch({
      '/api/auth/me': me('vendor_admin'),
      '/api/settings': (_u: string, init?: RequestInit) => { if (init?.method === 'PUT') values = { ...values, ...JSON.parse(String(init.body)) }; return { body: { vendor_id: 1, values } } },
    })
    render(wrap(<Signed><SettingsPage /></Signed>))
    expect(await screen.findByText(/currently go out/i)).toHaveTextContent('by SMS only')
    await userEvent.click(screen.getByRole('checkbox', { name: /^Email/ }))
    await waitFor(() => expect(screen.getByText(/currently go out/i)).toHaveTextContent('by SMS and by Email'))
    const put = f.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'PUT')!
    expect(JSON.parse(String((put[1] as RequestInit).body))).toMatchObject({ notify_email_enabled: true })
    await userEvent.click(screen.getByRole('checkbox', { name: /^SMS/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /^Email/ }))
    expect(await screen.findByText(/Both are off/i)).toBeInTheDocument()  // a clear warning when nothing will be sent
    expect(screen.getByText(/will not receive their OTP/i)).toBeInTheDocument()
  })
  it('vendor primary contact, email and address are required', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('super_admin'), '/api/vendors': { total: 0, items: [] } })
    render(wrap(<Signed><VendorsPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add vendor/i }))
    for (const name of [/^Primary contact/, /^Email/, /^Address/]) expect(await screen.findByLabelText(name)).toBeRequired()
    expect(screen.getByLabelText(/^Mobile/)).not.toBeRequired()
  })
  it('customer contact person and email are required', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/customers': { total: 0, items: [] } })
    render(wrap(<Signed><CustomersPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add customer/i }))
    for (const name of [/^Contact person/, /^Email/]) expect(await screen.findByLabelText(name)).toBeRequired()
  })
  it('employee site, shift and email are required', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add employee/i }))
    for (const name of [/^Site/, /^Shift/, /^Email/]) expect(await screen.findByLabelText(name)).toBeRequired()
  })
  it('vehicles say Vehicle Name, not Model', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/lookups': { vehicle_type: [], fuel_type: [], induction_type: [] }, '/api/vehicles': { total: 1, items: [{ id: 1, code: 'VEH-00001', vehicle_number: 'MH12AB1234', vehicle_code: 'V1', vehicle_type_id: 1, model: 'Dzire', capacity: 4, status: 'active', vendor_name: 'Alpha' }] } })
    render(wrap(<Signed><VehiclesPage /></Signed>))
    expect(await screen.findByRole('columnheader', { name: 'Vehicle Name' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Model' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /add vehicle/i }))
    expect(await screen.findByLabelText(/^Vehicle Name/)).toBeRequired()
    expect(screen.queryByLabelText(/^Model/)).not.toBeInTheDocument()
  })
  it('the notifications page has SMS and Email tabs', async () => {
    tokenStore.set('t')
    const f = mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/sms-logs': { total: 0, items: [] }, '/api/email-logs': { total: 0, items: [] } })
    render(wrap(<Signed><SmsLogsPage /></Signed>))
    expect(await screen.findByRole('tab', { name: 'SMS', selected: true })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Email' }))
    await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).startsWith('/api/email-logs'))).toBe(true))
    expect(screen.getByRole('tab', { name: 'Email', selected: true })).toBeInTheDocument()
  })
})

describe('operators work for one customer', () => {
  const Signed = ({ children }: { children: ReactNode }) => (useAuth().user ? <>{children}</> : null)
  const tagged = me('operator', { customer_id: 7, customer_name: 'Acme Corp' })

  it('the add-employee form names the customer instead of asking for it', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': tagged, '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [{ id: 7, name: 'Acme Corp' }] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add employee/i }))
    expect(await screen.findByRole('dialog', { name: 'Add employee for Acme Corp' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Customer/)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^Site/)).toBeInTheDocument()                    // the dependent lists still load for that customer
    expect(screen.queryByRole('columnheader', { name: 'Customer' })).not.toBeInTheDocument()
  })
  it('an admin still picks the customer', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add employee/i }))
    expect(await screen.findByLabelText(/^Customer/)).toBeRequired()
    expect(screen.getByRole('dialog', { name: 'Add employee' })).toBeInTheDocument()
  })
  it('the trip request names the customer and has no customer field', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': tagged, '/api/customers': { items: [{ id: 7, name: 'Acme Corp', vendor_id: 1 }] }, '/api/sites': { items: [] }, '/api/shifts': { items: [] }, '/api/employees': { items: [] } })
    render(wrap(<Signed><Routes><Route path="/trips/new" element={<TripFormPage />} /></Routes></Signed>, '/trips/new'))
    expect(await screen.findByRole('heading', { name: 'Request a trip for Acme Corp' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Customer/)).not.toBeInTheDocument()
  })
  it('an operator with no customer is told to ask their admin', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('operator'), '/api/employees': { total: 0, items: [] }, '/api/customers': { items: [] } })
    render(wrap(<Signed><EmployeesPage /></Signed>))
    expect(await screen.findByText(/not linked to a customer yet/i)).toBeInTheDocument()
  })
  it('creating an Operator requires choosing their customer', async () => {
    tokenStore.set('t')
    mockFetch({ '/api/auth/me': me('vendor_admin'), '/api/users': { total: 0, items: [] }, '/api/customers': { items: [{ id: 7, code: 'C1', name: 'Acme Corp' }] } })
    render(wrap(<Signed><UsersPage /></Signed>))
    await userEvent.click(await screen.findByRole('button', { name: /add user/i }))
    expect(screen.queryByLabelText(/^Customer/)).not.toBeInTheDocument()          // only once the role is Operator
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'operator')
    const field = await screen.findByLabelText(/^Customer/)
    expect(field).toBeRequired()
    expect(await screen.findByRole('option', { name: 'Acme Corp (C1)' })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'driver')
    expect(screen.queryByLabelText(/^Customer/)).not.toBeInTheDocument()
  })
})

describe('dialogs', () => {
  it('render at the top of the page, not inside the card they were opened from', () => {
    const { container } = render(<div className="card" style={{ transform: 'translateY(2px)', overflow: 'hidden' }}><Modal title="Add vehicle" onClose={() => {}}><p>form</p></Modal></div>)
    const dialog = screen.getByRole('dialog', { name: 'Add vehicle' })
    expect(container.contains(dialog)).toBe(false) // not trapped in the card
    expect(dialog.closest('.modal-scrim')?.parentElement).toBe(document.body)
  })
  it('Escape closes only the topmost dialog and the page behind does not scroll', async () => {
    const closed: string[] = []
    const { unmount } = render(<><Modal title="Outer" onClose={() => closed.push('outer')}><p>a</p></Modal><Modal title="Inner" onClose={() => closed.push('inner')}><p>b</p></Modal></>)
    expect(document.body.style.overflow).toBe('hidden')
    await userEvent.keyboard('{Escape}')
    expect(closed).toEqual(['inner'])
    unmount()
    expect(document.body.style.overflow).not.toBe('hidden')
  })
})

describe('components', () => {
  it('cancel dialog requires a reason', async () => {
    render(wrap(<CancelTripModal trip={{ id: 1, code: 'TRP-000001' }} onClose={() => {}} onDone={() => {}} />))
    const btn = screen.getByRole('button', { name: 'Cancel trip' })
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/reason/i), 'no')
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/reason/i), ' longer reason')
    await waitFor(() => expect(btn).toBeEnabled())
  })
  it('every chart can be viewed as a table', async () => {
    render(<ChartCard title="Trips by status" data={[{ label: 'Assigned', value: 3 }]}><div>the chart</div></ChartCard>)
    expect(screen.getByText('the chart')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show table' }))
    expect(screen.getByRole('table')).toHaveTextContent('Assigned')
    expect(screen.queryByText('the chart')).not.toBeInTheDocument()
  })
  it('shows an empty state instead of an empty chart', () => {
    render(<ChartCard title="X" data={[{ label: 'a', value: 0 }]}><div>the chart</div></ChartCard>)
    expect(screen.getByText('No data for this period.')).toBeInTheDocument()
  })
  it('compliance states are words, not just colours', () => {
    render(<><StateBadge state="expired" /><StateBadge state="expiring" days={5} /><StateBadge state="valid" /></>)
    expect(screen.getByText('Expired')).toBeInTheDocument()
    expect(screen.getByText('About to expire')).toBeInTheDocument()
    expect(screen.getByText('Valid')).toBeInTheDocument()
  })
})
