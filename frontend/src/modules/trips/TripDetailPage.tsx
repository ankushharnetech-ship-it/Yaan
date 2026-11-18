import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Info, KeyRound, Pencil, UserCheck, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, PageHead } from '../../components/ui'
import { api } from '../../services/api'
import { TripNotifications } from '../notifications/SmsComponents'
import { CancelTripModal, fmtDateTime, isOpen, STATUS_LABEL, TripStatusBadge, type Trip, type TripStatus } from './shared'

export function TripDetailPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [cancelling, setCancelling] = useState(false)
  const { data: t, isLoading, isError } = useQuery({ queryKey: ['trip', id], queryFn: () => api<Trip>(`/trips/${id}`) })

  if (isLoading) return <p className="muted">Loading…</p>
  if (isError || !t) return <div className="alert alert-danger">Trip not found. <Link to="/trips">Back to trips</Link></div>
  const awaiting = t.status === 'scheduled'
  const pct = t.vehicle_capacity ? Math.min(100, Math.round((t.required_capacity / t.vehicle_capacity) * 100)) : 0

  return (
    <>
      <p style={{ margin: '0 0 8px' }}><Link to="/trips"><ArrowLeft size={14} /> Trips</Link></p>
      <PageHead
        title={t.code}
        subtitle={`${t.customer_name} · ${t.site_name} · ${t.trip_type}`}
        actions={<>
          <TripStatusBadge status={t.status} />
          {t.can_assign && <button className="btn btn-primary" onClick={() => nav(`/trips/${t.id}/assign`)}><UserCheck size={15} /> {awaiting ? 'Assign driver & vehicle' : 'Change driver / vehicle'}</button>}
          {t.can_edit && <button className="btn" onClick={() => nav(`/trips/${t.id}/edit`)}><Pencil size={15} /> Edit</button>}
          {t.can_cancel && isOpen(t.status) && <button className="btn" onClick={() => setCancelling(true)}><XCircle size={15} /> {awaiting ? (t.can_assign ? 'Reject request' : 'Cancel request') : 'Cancel trip'}</button>}
        </>}
      />
      {awaiting && (
        <div className="alert alert-warning" style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Info size={16} aria-hidden style={{ flexShrink: 0, marginTop: 2 }} />
          <span><strong>Awaiting assignment.</strong> Requested by {t.created_by}. {t.can_assign ? 'Assign an available driver and vehicle to confirm this trip.' : 'A Vendor Admin will assign a driver and vehicle; the driver and employees are notified once they do.'}</span>
        </div>
      )}
      {t.status === 'cancelled' && (
        <div className="alert alert-danger">Cancelled by {t.cancelled_by} on {fmtDateTime(t.cancelled_at!)}. Reason: {t.cancellation_reason}</div>
      )}
      <div className="grid-2">
        <div className="card section">
          <h2>Schedule & route</h2>
          <dl className="kv">
            <dt>Start Trip</dt><dd>{fmtDateTime(t.scheduled_start)}</dd>
            <dt>End Trip</dt><dd>{fmtDateTime(t.scheduled_end)}</dd>
            <dt>Shift</dt><dd>{t.shift_name ?? '—'}</dd>
            <dt>Route</dt><dd>{t.route_name ?? '—'}</dd>
            <dt>Pickup</dt><dd>{t.pickup_address}</dd>
            <dt>Drop</dt><dd>{t.drop_address}</dd>
            <dt>Instructions</dt><dd>{t.special_instructions ?? '—'}</dd>
            <dt>Created by</dt><dd>{t.created_by}</dd>
          </dl>
        </div>
        <div className="card section">
          <h2>Driver & vehicle</h2>
          <dl className="kv">
            <dt>Driver</dt><dd>{t.driver_name ?? <span className="muted">Not assigned yet</span>}{t.driver_contact && <span className="muted"> · {t.driver_contact}</span>}</dd>
            <dt>Vehicle</dt><dd>{t.vehicle_number ?? <span className="muted">Not assigned yet</span>}</dd>
            <dt>Capacity</dt><dd>{t.vehicle_capacity ? `${t.vehicle_capacity} seats` : '—'}</dd>
            <dt>Seats needed</dt><dd>{t.required_capacity} ({t.passenger_count} passenger{t.passenger_count > 1 ? 's' : ''}{t.escort_required ? ' + 1 escort seat' : ''})</dd>
          </dl>
          {t.vehicle_capacity && <div className="meter" style={{ marginTop: 12 }} aria-label={`${pct}% of seats used`}><div style={{ width: `${pct}%` }} /></div>}
        </div>
        <div className="card section">
          <h2>Passengers ({t.passenger_count})</h2>
          {t.passengers.some((p) => p.otp) && (
            <div className="alert alert-warning" style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <KeyRound size={16} aria-hidden style={{ flexShrink: 0, marginTop: 2 }} />
              <span>Only you can see these drop-off OTPs. Each employee also gets theirs by notification. The driver asks the employee for it at the drop point, so <strong>never tell the driver</strong>.</span>
            </div>
          )}
          {['started', 'completed'].includes(t.status) && <p className="muted" style={{ marginTop: 0 }}>{t.drops_resolved} of {t.passenger_count} dropped</p>}
          <ol style={{ margin: 0, paddingLeft: 20, display: 'grid', gap: 12 }}>
            {t.passengers.map((p) => (
              <li key={p.employee_id}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <strong>{p.name}</strong>{p.mobile && <span className="muted">· {p.mobile}</span>}
                  {p.drop_status === 'verified' && <Badge tone="success">Dropped · OTP verified</Badge>}
                  {p.drop_status === 'not_dropped' && <Badge tone="danger">Not dropped</Badge>}
                  {p.drop_status === 'pending' && ['started'].includes(t.status) && <Badge tone="warning">{p.otp_locked ? 'OTP locked' : 'Waiting'}</Badge>}
                </div>
                {p.address && <div className="muted" style={{ fontSize: 13 }}>Address: {p.address}</div>}
                {p.otp && (
                  <div className="otp-box" aria-label={`OTP for ${p.name}`}>
                    <span className="muted">Drop-off OTP</span> <strong className="otp-code">{p.otp}</strong>
                  </div>
                )}
                {p.drop_status === 'not_dropped' && <div className="reason" style={{ fontSize: 13 }}>Reason: {p.not_dropped_reason}</div>}
              </li>
            ))}
          </ol>
        </div>
        <div className="card section">
          <h2>Status history</h2>
          <ul className="timeline">
            {t.history?.map((h, i) => (
              <li key={i}>
                <strong>{STATUS_LABEL[h.to as TripStatus] ?? h.to}</strong>
                <div className="muted" style={{ fontSize: 13 }}>{fmtDateTime(h.at)} · {h.by}{h.note ? ` · ${h.note}` : ''}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="card section">
        <h2>Notifications</h2>
        {awaiting ? <p className="muted" style={{ margin: 0 }}>Nothing sent yet. The driver and employees are notified (and each employee gets their OTP) when a Vendor Admin assigns a driver and vehicle.</p> : <TripNotifications tripId={t.id} />}
      </div>
      {cancelling && <CancelTripModal reject={awaiting && t.can_assign} trip={t} onClose={() => setCancelling(false)} onDone={() => { setCancelling(false); qc.invalidateQueries({ queryKey: ['trip', id] }); qc.invalidateQueries({ queryKey: ['trips'] }) }} />}
    </>
  )
}
