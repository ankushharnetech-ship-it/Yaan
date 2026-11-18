import { Clock, MapPin } from 'lucide-react'
import { useState } from 'react'
import { CrudPage, type Column } from '../../components/CrudPage'
import { Modal } from '../../components/ui'
import { lookupLabel, lookupOptions, useLookups } from '../../services/lookups'
import { useAuth } from '../auth/AuthContext'

const GENDERS = [{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }, { value: 'other', label: 'Other' }]
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const dash = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))
const full = (r: Record<string, any>) => [r.first_name, r.middle_name, r.last_name].filter(Boolean).join(' ') // eslint-disable-line @typescript-eslint/no-explicit-any

function useCanWrite(...roles: string[]) {
  const { user } = useAuth()
  return !!user && roles.includes(user.role)
}

// ---------------- Vendors (Super Admin) ----------------
export function VendorsPage() {
  return (
    <CrudPage
      title="Vendors" noun="vendor" subtitle="Transport vendors (tenants) on the platform." endpoint="/vendors" canWrite
      columns={[
        { header: 'Name', cell: (r) => <strong>{r.name}</strong> }, { header: 'Code', cell: (r) => r.code },
        { header: 'Contact', cell: (r) => dash(r.contact_name) }, { header: 'Email', cell: (r) => dash(r.email) }, { header: 'Mobile', cell: (r) => dash(r.mobile) },
      ]}
      fields={[
        { key: 'name', label: 'Vendor name', required: true }, { key: 'code', label: 'Vendor code', required: true, hint: 'Letters, numbers, - and _' },
        { key: 'contact_name', label: 'Primary contact', required: true }, { key: 'email', label: 'Email', type: 'email', required: true },
        { key: 'mobile', label: 'Mobile', type: 'tel' }, { key: 'address', label: 'Address', type: 'textarea', required: true },
      ]}
    />
  )
}

// ---------------- Customers + sites ----------------
export function CustomersPage() {
  const canWrite = useCanWrite('super_admin', 'vendor_admin')
  const [sitesFor, setSitesFor] = useState<{ id: number; name: string } | null>(null)
  const [shiftsFor, setShiftsFor] = useState<{ id: number; name: string } | null>(null)
  return (
    <>
      <CrudPage
        title="Customers" noun="customer" subtitle="Companies served by your vendor, and their offices." endpoint="/customers" canWrite={canWrite} vendorScoped
        columns={[
          { header: 'Code', cell: (r) => r.code }, { header: 'Name', cell: (r) => <strong>{r.name}</strong> },
          { header: 'Contact', cell: (r) => dash(r.contact_person) }, { header: 'Phone', cell: (r) => dash(r.phone) },
          { header: 'Sites', cell: (r) => r.site_count },
        ]}
        fields={[
          { key: 'code', label: 'Customer code', required: true }, { key: 'name', label: 'Customer name', required: true },
          { key: 'contact_person', label: 'Contact person', required: true }, { key: 'email', label: 'Email', type: 'email', required: true },
          { key: 'phone', label: 'Phone', type: 'tel' },
          { key: 'address', label: 'Address', type: 'textarea', required: true, wide: true },
          { key: 'latitude', label: 'Latitude', type: 'number', required: true, hint: 'Between -90 and 90, e.g. 18.5204' },
          { key: 'longitude', label: 'Longitude', type: 'number', required: true, hint: 'Between -180 and 180, e.g. 73.8567' },
        ]}
        rowExtra={(r) => (
          <>
            <button className="btn" onClick={() => setSitesFor({ id: r.id, name: r.name })} title="Manage offices"><MapPin size={15} /> Sites</button>
            <button className="btn" onClick={() => setShiftsFor({ id: r.id, name: r.name })} title="Manage shift timings"><Clock size={15} /> Shifts</button>
          </>
        )}
      />
      {shiftsFor && (
        <Modal title={`Shifts — ${shiftsFor.name}`} onClose={() => setShiftsFor(null)} wide>
          <CrudPage
            embedded title="Shifts" noun="shift" endpoint="/shifts" canWrite={canWrite}
            fixedQuery={{ customer_id: String(shiftsFor.id) }} fixedBody={{ customer_id: shiftsFor.id }}
            columns={[
              { header: 'Name', cell: (r) => <strong>{r.name}</strong> },
              { header: 'Timing', cell: (r) => `${String(r.start_time).slice(0, 5)} – ${String(r.end_time).slice(0, 5)}` },
            ]}
            fields={[
              { key: 'name', label: 'Shift name', required: true, hint: 'e.g. Morning, Night' },
              { key: 'start_time', label: 'Start time', type: 'time', required: true },
              { key: 'end_time', label: 'End time', type: 'time', required: true, hint: 'Earlier than start = overnight shift' },
            ]}
          />
        </Modal>
      )}
      {sitesFor && (
        <Modal title={`Offices — ${sitesFor.name}`} onClose={() => setSitesFor(null)} wide>
          <CrudPage
            embedded title="Sites" noun="site" endpoint="/sites" canWrite={canWrite}
            fixedQuery={{ customer_id: String(sitesFor.id) }} fixedBody={{ customer_id: sitesFor.id }}
            columns={[
              { header: 'Name', cell: (r) => <strong>{r.name}</strong> }, { header: 'City', cell: (r) => dash(r.city) },
              { header: 'Address', cell: (r) => r.address },
            ]}
            fields={[
              { key: 'name', label: 'Office name', required: true }, { key: 'city', label: 'City' },
              { key: 'address', label: 'Address', type: 'textarea', required: true },
              { key: 'latitude', label: 'Latitude', type: 'number' }, { key: 'longitude', label: 'Longitude', type: 'number' },
            ]}
          />
        </Modal>
      )}
    </>
  )
}

// ---------------- Employees ----------------
const customerCol: Column = { header: 'Customer', cell: (r) => r.customer_name }
export function EmployeesPage() {
  // Operators may add and edit employees of their vendor; only admins can deactivate/reactivate them.
  const canWrite = useCanWrite('super_admin', 'vendor_admin', 'operator')
  const isAdmin = useCanWrite('super_admin', 'vendor_admin')
  const { user } = useAuth()
  const mine = user?.role === 'operator' ? user.customer_id ?? null : null // an Operator works for one customer
  return (
    <>
    {user?.role === 'operator' && !mine && <div className="alert alert-warning">Your account is not linked to a customer yet, so you cannot add employees. Ask your administrator to assign one.</div>}
    <CrudPage
      title="Employees" noun="employee" subtitle="Passengers who travel on trips. They don't need a login." endpoint="/employees" canWrite={canWrite} vendorScoped statusToggle={isAdmin}
      fixedFields={mine ? { customer_id: String(mine) } : undefined} titleFor={mine ? user?.customer_name ?? undefined : undefined}
      filters={[
        ...(mine ? [] : [{ key: 'customer_id', label: 'All customers', remotePath: '/customers' }]),
        { key: 'gender', label: 'Any gender', options: GENDERS },
      ]}
      columns={[
        { header: 'Code', cell: (r) => r.employee_code }, { header: 'Name', cell: (r) => <strong>{r.first_name} {r.last_name}</strong> },
        ...(mine ? [] : [customerCol]), { header: 'Site', cell: (r) => dash(r.site_name) },
        { header: 'Mobile', cell: (r) => r.mobile }, { header: 'Gender', cell: (r) => cap(r.gender) },
      ]}
      fields={[
        { key: 'customer_id', label: 'Customer', required: true, numeric: true, createOnly: true, type: 'select',
          remote: { path: (f) => (f.vendor_id !== undefined && !f.vendor_id ? null : `/customers?status=active&limit=200${f.vendor_id ? `&vendor_id=${f.vendor_id}` : ''}`), value: (r) => r.id, label: (r) => r.name } },
        { key: 'site_id', label: 'Site / office', required: true, numeric: true, type: 'select', hint: 'Select a customer first',
          remote: { path: (f) => (f.customer_id ? `/sites?customer_id=${f.customer_id}&status=active` : null), value: (r) => r.id, label: (r) => `${r.name}${r.city ? ` — ${r.city}` : ''}` } },
        { key: 'shift_id', label: 'Shift', required: true, numeric: true, type: 'select', hint: 'Select a customer first',
          remote: { path: (f) => (f.customer_id ? `/shifts?customer_id=${f.customer_id}&status=active` : null), value: (r) => r.id, label: (r) => `${r.name} (${String(r.start_time).slice(0, 5)}–${String(r.end_time).slice(0, 5)})` } },
        { key: 'employee_code', label: 'Employee ID', required: true }, { key: 'department', label: 'Department' },
        { key: 'first_name', label: 'First name', required: true }, { key: 'last_name', label: 'Last name', required: true },
        { key: 'mobile', label: 'Mobile', type: 'tel', required: true, hint: 'Trip SMS are sent here' },
        { key: 'email', label: 'Email', type: 'email', required: true, hint: 'Trip emails and OTPs can be sent here' },
        { key: 'gender', label: 'Gender', type: 'select', required: true, options: GENDERS, hint: 'Used for the escort-seat rule' },
        { key: 'address', label: 'Address', type: 'textarea', required: true, wide: true, hint: 'Home address. Used as the pickup point on Pickup trips and the drop point on Drop trips.' },
        { key: 'latitude', label: 'Latitude', type: 'number', required: true, hint: 'Between -90 and 90, e.g. 18.5204' },
        { key: 'longitude', label: 'Longitude', type: 'number', required: true, hint: 'Between -180 and 180, e.g. 73.8567' },
      ]}
    />
    </>
  )
}

// ---------------- Drivers ----------------
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => ({ value: d, label: d }))
const LANGS = ['English', 'Hindi', 'Marathi', 'Gujarati', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Bengali', 'Punjabi'].map((d) => ({ value: d, label: d }))

export function DriversPage() {
  const canWrite = useCanWrite('super_admin', 'vendor_admin')
  const { data: lk } = useLookups()
  if (!lk) return <p className="muted">Loading…</p>
  return (
    <CrudPage
      title="Drivers" noun="driver" subtitle="Driver master records. Create a driver here, then onboard their login under Users." endpoint="/drivers" canWrite={canWrite} vendorScoped
      columns={[
        { header: 'ID', cell: (r) => r.code }, { header: 'Name', cell: (r) => <strong>{full(r)}</strong> },
        { header: 'Contact', cell: (r) => r.contact_number }, { header: 'Licence', cell: (r) => `${lookupLabel(lk, 'license_type', r.license_type_id)} · ${r.license_number}` },
        { header: 'Login', cell: (r) => (r.has_login ? 'Yes' : 'No') },
      ]}
      fields={[
        { type: 'section', label: 'Personal details' },
        { key: 'first_name', label: 'First name', required: true }, { key: 'middle_name', label: 'Middle name' },
        { key: 'last_name', label: 'Last name', required: true }, { key: 'contact_number', label: 'Contact number', type: 'tel', required: true }, { key: 'email', label: 'Email', type: 'email', required: true, hint: 'Used for email notifications' },
        { key: 'gender', label: 'Gender', type: 'select', required: true, options: GENDERS },
        { key: 'date_of_birth', label: 'Date of birth', type: 'date' }, { key: 'emergency_contact', label: 'Emergency contact', type: 'tel', required: true },
        { key: 'languages', label: 'Languages known', type: 'multi', options: LANGS },
        { key: 'home_address', label: 'Home address', type: 'textarea', required: true }, { key: 'locality', label: 'Locality' },
        { type: 'section', label: 'Licence & employment' },
        { key: 'license_type_id', label: 'Licence type', type: 'select', required: true, numeric: true, options: lookupOptions(lk, 'license_type') },
        { key: 'license_number', label: 'Licence number', required: true },
        { key: 'date_of_joining', label: 'Date of joining', type: 'date', required: true }, { key: 'experience_months', label: 'Experience (months)', type: 'number', required: true },
        { key: 'induction_type_id', label: 'Induction type', type: 'select', numeric: true, options: lookupOptions(lk, 'induction_type') },
        { key: 'induction_date', label: 'Induction date', type: 'date' },
        { key: 'default_vehicle_id', label: 'Default vehicle', numeric: true, type: 'select', hint: 'Optional',
          remote: { path: (f) => (f.vendor_id !== undefined && !f.vendor_id ? null : `/vehicles?status=active&limit=200${f.vendor_id ? `&vendor_id=${f.vendor_id}` : ''}`), value: (r) => r.id, label: (r) => `${r.vehicle_number} (${r.model})` } },
        { key: 'rest_days', label: 'Rest days', type: 'multi', options: DAYS },
        { key: 'status_comment', label: 'Status comment', type: 'textarea' },
      ]}
    />
  )
}

// ---------------- Vehicles ----------------
export function VehiclesPage() {
  const canWrite = useCanWrite('super_admin', 'vendor_admin')
  const { data: lk } = useLookups()
  if (!lk) return <p className="muted">Loading…</p>
  return (
    <CrudPage
      title="Vehicles" noun="vehicle" subtitle="Fleet master records. Capacity decides which trips a vehicle can take." endpoint="/vehicles" canWrite={canWrite} vendorScoped
      filters={[{ key: 'vehicle_type_id', label: 'All types', options: lookupOptions(lk, 'vehicle_type') }]}
      columns={[
        { header: 'Number', cell: (r) => <strong>{r.vehicle_number}</strong> }, { header: 'Code', cell: (r) => r.vehicle_code },
        { header: 'Type', cell: (r) => lookupLabel(lk, 'vehicle_type', r.vehicle_type_id) }, { header: 'Vehicle Name', cell: (r) => r.model },
        { header: 'Capacity', cell: (r) => `${r.capacity} seats` },
      ]}
      fields={[
        { key: 'vehicle_number', label: 'Vehicle number', required: true, hint: 'e.g. MH12AB1234' }, { key: 'vehicle_code', label: 'Vehicle code', required: true },
        { key: 'vehicle_type_id', label: 'Vehicle type', type: 'select', required: true, numeric: true, options: lookupOptions(lk, 'vehicle_type') },
        { key: 'model', label: 'Vehicle Name', required: true, hint: 'e.g. Dzire, Innova Crysta, Tempo Traveller' }, { key: 'make', label: 'Make' },
        { key: 'capacity', label: 'Passenger capacity', type: 'number', required: true, hint: 'Seats available for passengers' },
        { key: 'fuel_type_id', label: 'Fuel type', type: 'select', numeric: true, options: lookupOptions(lk, 'fuel_type') },
        { key: 'chassis_number', label: 'Chassis number' }, { key: 'date_of_joining', label: 'Date of joining', type: 'date' },
        { key: 'induction_type_id', label: 'Induction type', type: 'select', numeric: true, options: lookupOptions(lk, 'induction_type') },
        { key: 'induction_date', label: 'Induction date', type: 'date' },
        { key: 'billing_profile', label: 'Billing profile' }, { key: 'gps_imei', label: 'GPS / IMEI', hint: 'Optional — not needed for this release' },
        { key: 'shed_location', label: 'Shed location', type: 'textarea' }, { key: 'locality', label: 'Locality' },
      ]}
    />
  )
}
