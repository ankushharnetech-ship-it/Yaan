import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Flag, Map as MapIcon, MapPin, Pencil, Plus, UserCheck, XCircle } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PageHead } from '../../components/ui'
import { api } from '../../services/api'
import { useAuth } from '../auth/AuthContext'
import { SmsBadge } from '../notifications/SmsComponents'
import { DriverTripsPage } from './DriverTripsPage'
import { TripMapModal } from './TripMapModal'
import { CancelTripModal, fmtDate, fmtTime, TripStatusBadge, type Trip } from './shared'

const VIEWS = [
  ['all', 'All'], ['awaiting', 'Awaiting assignment'], ['upcoming', 'Upcoming'], ['assigned', 'Assigned'], ['accepted', 'Accepted'],
  ['ongoing', 'Ongoing'], ['completed', 'Completed'], ['cancelled', 'Cancelled'],
] as const

export function TripsPage() {
  const { user } = useAuth()
  return user?.role === 'driver' ? <DriverTripsPage /> : <AdminTripsPage />
}

function Select({ label, value, onChange, path, labelOf }: { label: string; value: string; onChange: (v: string) => void; path: string; labelOf: (r: Record<string, string>) => string }) {
  const { data } = useQuery({ queryKey: [path, 'f'], queryFn: () => api<{ items: Record<string, string>[] }>(path) })
  return (
    <select className="input" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}</option>{data?.items.map((r) => <option key={r.id} value={r.id}>{labelOf(r)}</option>)}
    </select>
  )
}

function AdminTripsPage() {
  const { user } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [sp] = useSearchParams()
  const wanted = VIEWS.find(([k]) => k === sp.get('view'))?.[0]
  const [view, setView] = useState<(typeof VIEWS)[number][0]>(wanted ?? 'upcoming')
  const [f, setF] = useState<Record<string, string>>({})
  const [page, setPage] = useState(0)
  const [cancelling, setCancelling] = useState<Trip | null>(null)
  const [mapFor, setMapFor] = useState<Trip | null>(null)
  const limit = 15
  const set = (k: string) => (v: string) => { setF({ ...f, [k]: v }); setPage(0) }

  const params = new URLSearchParams({ view, limit: String(limit), offset: String(page * limit) })
  Object.entries(f).forEach(([k, v]) => v && params.set(k, v))
  const { data, isLoading, isError } = useQuery({ queryKey: ['trips', params.toString()], queryFn: () => api<{ total: number; items: Trip[] }>(`/trips?${params}`) })
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))
  const isOperator = user!.role === 'operator'

  return (
    <>
      <PageHead title="Trips"
        subtitle={isOperator ? 'Request trips for employees. A Vendor Admin assigns the driver and vehicle.' : 'Review requests, assign drivers and vehicles, and track every trip.'}
        actions={<button className="btn btn-primary" onClick={() => nav('/trips/new')}><Plus size={16} /> {isOperator ? 'Request trip' : 'Create trip'}</button>} />
      <div className="card">
        <div className="tabs" role="tablist">
          {VIEWS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={view === k} className={`tab ${view === k ? 'on' : ''}`} onClick={() => { setView(k); setPage(0) }}>{label}</button>
          ))}
        </div>
        <div className="toolbar">
          <input className="input" placeholder="Search Trip ID" aria-label="Search Trip ID" value={f.q ?? ''} onChange={(e) => set('q')(e.target.value)} />
          <input className="input" type="date" aria-label="From date" value={f.date_from ?? ''} onChange={(e) => set('date_from')(e.target.value)} />
          <input className="input" type="date" aria-label="To date" value={f.date_to ?? ''} onChange={(e) => set('date_to')(e.target.value)} />
          {user!.role === 'super_admin' && <Select label="All vendors" path="/vendors?limit=200" value={f.vendor_id ?? ''} onChange={set('vendor_id')} labelOf={(r) => r.name} />}
          <Select label="All customers" path="/customers?limit=200" value={f.customer_id ?? ''} onChange={set('customer_id')} labelOf={(r) => r.name} />
          <Select label="All drivers" path="/drivers?limit=200" value={f.driver_id ?? ''} onChange={set('driver_id')} labelOf={(r) => `${r.first_name} ${r.last_name}`} />
          <Select label="All vehicles" path="/vehicles?limit=200" value={f.vehicle_id ?? ''} onChange={set('vehicle_id')} labelOf={(r) => r.vehicle_number} />
        </div>
        {isLoading ? <p className="muted">Loading trips…</p> : isError ? <div className="alert alert-danger">Could not load trips.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Trip ID</th><th>Date</th><th>Time</th><th>Customer</th><th>Site</th><th>Pax</th><th>Driver</th><th>Vehicle</th><th>Status</th><th>Notified</th><th>Created by</th><th>Actions</th></tr></thead>
              <tbody>
                {data!.items.map((t) => (
                  <Fragment key={t.id}>
                  <tr className="row-open">
                    <td><Link to={`/trips/${t.id}`}><strong>{t.code}</strong></Link></td>
                    <td>{fmtDate(t.scheduled_start)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtTime(t.scheduled_start)} – {fmtTime(t.scheduled_end)}</td>
                    <td>{t.customer_name}</td><td>{t.site_name}</td>
                    <td>{t.passenger_count}{t.escort_required && <span title="Escort seat reserved" className="muted"> +1</span>}</td>
                    <td>{t.driver_name ?? <span className="muted">—</span>}</td><td>{t.vehicle_number ?? <span className="muted">—</span>}</td>
                    <td><TripStatusBadge status={t.status} /></td>
                    <td><SmsBadge status={t.notify_status} /></td><td>{t.created_by}</td>
                    <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: 6 }}>
                      <button className="btn" aria-label={`View ${t.code}`} title="View" onClick={() => nav(`/trips/${t.id}`)}><Eye size={15} /></button>
                      <button className="btn" aria-label={`Map for ${t.code}`} title="View route on map" onClick={() => setMapFor(t)}><MapIcon size={15} /></button>
                      {t.can_assign && (
                        <button className="btn btn-primary" aria-label={`${t.status === 'scheduled' ? 'Assign' : 'Change driver or vehicle for'} ${t.code}`} title={t.status === 'scheduled' ? 'Assign driver & vehicle' : 'Change driver / vehicle'} onClick={() => nav(`/trips/${t.id}/assign`)}><UserCheck size={15} />{t.status === 'scheduled' && ' Assign'}</button>
                      )}
                      {t.can_edit && (
                        <button className="btn" aria-label={`Edit ${t.code}`} title="Edit" onClick={() => nav(`/trips/${t.id}/edit`)}><Pencil size={15} /></button>
                      )}
                      {t.can_cancel && (
                        <button className="btn" aria-label={`${t.status === 'scheduled' && t.can_assign ? 'Reject' : 'Cancel'} ${t.code}`} title={t.status === 'scheduled' ? (t.can_assign ? 'Reject request' : 'Cancel request') : 'Cancel trip'} onClick={() => setCancelling(t)}><XCircle size={15} /></button>
                      )}
                    </td>
                  </tr>
                  {/* Always visible: pickup and drop for every trip, so nobody has to open the trip to see them */}
                  <tr className="drawer-row">
                    <td colSpan={12}>
                      <div className="drawer" aria-label={`Pickup and drop for ${t.code}`}>
                        <div><span className="drawer-label"><MapPin size={14} aria-hidden /> Pickup</span><span>{t.pickup_address}</span></div>
                        <div><span className="drawer-label"><Flag size={14} aria-hidden /> Drop</span><span>{t.drop_address}</span></div>
                      </div>
                    </td>
                  </tr>
                  </Fragment>
                ))}
                {!data!.items.length && <tr><td colSpan={12} className="muted" style={{ textAlign: 'center', padding: 36 }}>No trips match these filters.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
          <span className="muted">{data?.total ?? 0} trips</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
      </div>
      {mapFor && <TripMapModal tripId={mapFor.id} code={mapFor.code} onClose={() => setMapFor(null)} />}
      {cancelling && <CancelTripModal reject={cancelling.status === 'scheduled' && cancelling.can_assign} trip={cancelling} onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); qc.invalidateQueries({ queryKey: ['trips'] }); qc.invalidateQueries({ queryKey: ['dash'] }) }} />}
    </>
  )
}
